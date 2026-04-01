#
# SPDX-FileCopyrightText: 2026 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
import logging
import math
import os
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from enum import Enum
from threading import Event, Thread
from time import sleep
from typing import Any

import niquests
from langchain.llms.base import LLM
from langchain.schema import Document
from nc_py_api import NextcloudApp, NextcloudException
from niquests import JSONDecodeError, RequestException
from pydantic import ValidationError

from .chain.context import do_doc_search, get_context_chunks, get_context_docs
from .chain.ingest.injest import embed_sources
from .chain.one_shot import process_context_query
from .chain.query_proc import get_pruned_query
from .chain.types import ContextException, EnrichedSourceList, LLMOutput, ScopeList, ScopeType, SearchResult
from .dyn_loader import LLMModelLoader, VectorDBLoader
from .network_em import NetworkEmbeddings
from .types import (
	ActionsQueueItems,
	ActionType,
	AppRole,
	EmbeddingException,
	FilesQueueItems,
	IndexingError,
	LoaderException,
	ReceivedFileItem,
	SourceItem,
	TConfig,
)
from .utils import SubprocessKilledError, exec_in_proc, get_app_role
from .vectordb.base import BaseVectorDB
from .vectordb.service import (
	decl_update_access,
	delete_by_provider,
	delete_by_source,
	delete_user,
	update_access,
	update_access_provider,
)
from .vectordb.types import DbException, SafeDbException

APP_ROLE = get_app_role()
THREADS = {}
THREAD_STOP_EVENT = Event()
LOGGER = logging.getLogger('ccb.task_fetcher')
FILES_INDEXING_BATCH_SIZE = 16  # theoretical max RAM usage: 16 * 100 MiB, todo: config?
if os.getenv('GITHUB_ACTIONS'):
	FILES_INDEXING_BATCH_SIZE = 4
MIN_FILES_PER_CPU = 4
if os.getenv('GITHUB_ACTIONS'):
	MIN_FILES_PER_CPU = 2
# divides the batch into these many chunks
PARALLEL_FILE_PARSING_COUNT = max(1, (os.cpu_count() or 2) - 1)  # todo: config?
if os.getenv('GITHUB_ACTIONS'):
	# Keep CI memory usage predictable and avoid OOM-killed workers.
	PARALLEL_FILE_PARSING_COUNT = max(1, min(PARALLEL_FILE_PARSING_COUNT, 2))
LOGGER.info(f'Using {PARALLEL_FILE_PARSING_COUNT} parallel file parsing workers')
ACTIONS_BATCH_SIZE = 512  # todo: config?
POLLING_COOLDOWN = 30
TRIGGER = Event()
CHECK_INTERVAL = 5
CHECK_INTERVAL_WITH_TRIGGER = 5 * 60
CHECK_INTERVAL_ON_ERROR = 15
CONTEXT_LIMIT=20


class ThreadType(Enum):
	FILES_INDEXING = 'files_indexing'
	UPDATES_PROCESSING = 'updates_processing'
	REQUEST_PROCESSING = 'request_processing'


def files_indexing_thread(app_config: TConfig, app_enabled: Event) -> None:
	try:
		vectordb_loader = VectorDBLoader(app_config)
	except LoaderException as e:
		LOGGER.error('Error initializing vector DB loader, files indexing thread will not start:', exc_info=e)
		return

	def _embed_one(db_id: int, item: SourceItem | ReceivedFileItem) -> tuple[int, IndexingError | None]:
		"""Run embed_sources for a single item in its own subprocess. Returns (db_id, error_or_None)."""
		try:
			result = exec_in_proc(
				target=embed_sources,
				args=(vectordb_loader, app_config, {db_id: item}),
			)
			return db_id, result.get(db_id)
		except SubprocessKilledError as e:
			LOGGER.error(
				'embed_sources subprocess killed for individual source %s — marking as non-retryable'
				' to prevent infinite OOM retry loop',
				item.reference, exc_info=e,
			)
			return db_id, IndexingError(error=f'Subprocess killed (OOM?): {e}', retryable=False)
		except Exception as e:
			err_name = {DbException: 'DB', EmbeddingException: 'Embedding'}.get(type(e), 'Unknown')
			LOGGER.error(
				'embed_sources raised a %s error for individual source %s, marking as retryable',
				err_name, item.reference, exc_info=e,
			)
			return db_id, IndexingError(error=str(e), retryable=True)

	def _load_sources(source_items: Mapping[int, SourceItem | ReceivedFileItem]) -> Mapping[int, IndexingError | None]:
		source_refs = [s.reference for s in source_items.values()]
		LOGGER.info('Starting embed_sources subprocess for %d source(s): %s', len(source_items), source_refs)
		try:
			result = exec_in_proc(
				target=embed_sources,
				args=(vectordb_loader, app_config, source_items),
			)
			errors = {k: v for k, v in result.items() if isinstance(v, IndexingError)}
			LOGGER.info(
				'embed_sources subprocess finished for %d source(s): %d succeeded, %d errored',
				len(source_items),
				len(result) - len(errors),
				len(errors),
				extra={'errors': errors} if errors else {},
			)
			return result
		except SubprocessKilledError as e:
			LOGGER.error(
				'embed_sources subprocess was killed (likely OOM) for %d source(s): %s',
				len(source_items), source_refs, exc_info=e,
			)
			if len(source_items) == 1:
				# Single-item subprocess was killed — mark non-retryable to break infinite OOM loop.
				LOGGER.error(
					'Single-item subprocess killed for %s — marking as non-retryable',
					source_refs,
				)
				return {db_id: IndexingError(error=f'Subprocess killed (OOM?): {e}', retryable=False)
					for db_id in source_items}

			# Multi-item batch: fall back to one subprocess per source to pinpoint the problematic file.
			LOGGER.warning(
				'Falling back to individual processing for %d sources to isolate any OOM-causing file(s)',
				len(source_items),
			)
			return dict(_embed_one(db_id, item) for db_id, item in source_items.items())

		except Exception as e:
			err_name = {DbException: 'DB', EmbeddingException: 'Embedding'}.get(type(e), 'Unknown')
			err = IndexingError(
				error=f'{err_name} Error: {e}',
				retryable=True,
			)
			LOGGER.error(
				'embed_sources subprocess raised a %s error for sources %s, marking all as retryable',
				err_name, source_refs, exc_info=e,
			)
			return dict.fromkeys(source_items, err)


	while True:
		if THREAD_STOP_EVENT.is_set():
			LOGGER.info('Files indexing thread is stopping due to stop event being set')
			return

		try:
			if not __check_em_server(app_config):
				sleep(POLLING_COOLDOWN)
				continue

			nc = NextcloudApp()
			q_items_res = nc.ocs(
				'GET',
				'/ocs/v2.php/apps/context_chat/queues/documents',
				params={ 'n': FILES_INDEXING_BATCH_SIZE }
			)

			try:
				q_items: FilesQueueItems = FilesQueueItems.model_validate(q_items_res)
			except ValidationError as e:
				raise Exception(f'Error validating queue items response: {e}\nResponse content: {q_items_res}') from e

			if not q_items.files and not q_items.content_providers:
				LOGGER.debug('No documents to index')
				sleep(POLLING_COOLDOWN)
				continue

			files_result = {}
			providers_result = {}

			# chunk file parsing for better file operation parallelism
			file_chunk_size = max(MIN_FILES_PER_CPU, math.ceil(len(q_items.files) / PARALLEL_FILE_PARSING_COUNT))
			file_chunks = [
				dict(list(q_items.files.items())[i:i+file_chunk_size])
				for i in range(0, len(q_items.files), file_chunk_size)
			]
			provider_chunk_size = max(
				MIN_FILES_PER_CPU,
				math.ceil(len(q_items.content_providers) / PARALLEL_FILE_PARSING_COUNT),
			)
			provider_chunks = [
				dict(list(q_items.content_providers.items())[i:i+provider_chunk_size])
				for i in range(0, len(q_items.content_providers), provider_chunk_size)
			]

			with ThreadPoolExecutor(
				max_workers=PARALLEL_FILE_PARSING_COUNT,
				thread_name_prefix='IndexingPool',
			) as executor:
				LOGGER.info(
					'Dispatching %d file chunk(s) and %d provider chunk(s) to %d IndexingPool worker(s)',
					len(file_chunks), len(provider_chunks), PARALLEL_FILE_PARSING_COUNT,
				)
				file_futures = [executor.submit(_load_sources, chunk) for chunk in file_chunks]
				provider_futures = [executor.submit(_load_sources, chunk) for chunk in provider_chunks]

				for i, future in enumerate(file_futures):
					LOGGER.debug('Waiting for file chunk %d/%d future to complete', i + 1, len(file_futures))
					files_result.update(future.result())
					LOGGER.debug('File chunk %d/%d future completed', i + 1, len(file_futures))
				for i, future in enumerate(provider_futures):
					LOGGER.debug('Waiting for provider chunk %d/%d future to complete', i + 1, len(provider_futures))
					providers_result.update(future.result())
					LOGGER.debug('Provider chunk %d/%d future completed', i + 1, len(provider_futures))

			if (
				any(isinstance(res, IndexingError) for res in files_result.values())
				or any(isinstance(res, IndexingError) for res in providers_result.values())
			):
				LOGGER.error('Some sources failed to index', extra={
					'file_errors': {
						db_id: error
						for db_id, error in files_result.items()
						if isinstance(error, IndexingError)
					},
					'provider_errors': {
						provider_id: error
						for provider_id, error in providers_result.items()
						if isinstance(error, IndexingError)
					},
				})
		except (
			niquests.exceptions.ConnectionError,
			niquests.exceptions.Timeout,
		) as e:
			LOGGER.info('Temporary error fetching documents to index, will retry:', exc_info=e)
			sleep(5)
			continue
		except Exception as e:
			LOGGER.exception('Error fetching documents to index:', exc_info=e)
			sleep(5)
			continue

		# delete the entries from the PHP side queue where indexing succeeded or the error is not retryable
		to_delete_files_db_ids = [
			db_id for db_id, result in files_result.items()
			if result is None or (isinstance(result, IndexingError) and not result.retryable)
		]
		to_delete_provider_db_ids = [
			db_id for db_id, result in providers_result.items()
			if result is None or (isinstance(result, IndexingError) and not result.retryable)
		]

		try:
			nc.ocs(
				'DELETE',
				'/ocs/v2.php/apps/context_chat/queues/documents/',
				json={
					'files': to_delete_files_db_ids,
					'content_providers': to_delete_provider_db_ids,
				},
			)
		except (
			niquests.exceptions.ConnectionError,
			niquests.exceptions.Timeout,
		) as e:
			LOGGER.info('Temporary error reporting indexing results, will retry:', exc_info=e)
			sleep(5)
			with suppress(Exception):
				nc = NextcloudApp()
				nc.ocs(
					'DELETE',
					'/ocs/v2.php/apps/context_chat/queues/documents/',
					json={
						'files': to_delete_files_db_ids,
						'content_providers': to_delete_provider_db_ids,
					},
				)
			continue
		except Exception as e:
			LOGGER.exception('Error reporting indexing results:', exc_info=e)
			sleep(5)
			continue



def updates_processing_thread(app_config: TConfig, app_enabled: Event) -> None:
	try:
		vectordb_loader = VectorDBLoader(app_config)
	except LoaderException as e:
		LOGGER.error('Error initializing vector DB loader, files indexing thread will not start:', exc_info=e)
		return

	while True:
		if THREAD_STOP_EVENT.is_set():
			LOGGER.info('Updates processing thread is stopping due to stop event being set')
			return

		try:
			nc = NextcloudApp()
			q_items_res = nc.ocs(
				'GET',
				'/ocs/v2.php/apps/context_chat/queues/actions',
				params={ 'n': ACTIONS_BATCH_SIZE }
			)

			try:
				q_items: ActionsQueueItems = ActionsQueueItems.model_validate(q_items_res)
			except ValidationError as e:
				raise Exception(f'Error validating queue items response: {e}\nResponse content: {q_items_res}') from e
		except (
			niquests.exceptions.ConnectionError,
			niquests.exceptions.Timeout,
		) as e:
			LOGGER.info('Temporary error fetching updates to process, will retry:', exc_info=e)
			sleep(5)
			continue
		except Exception as e:
			LOGGER.exception('Error fetching updates to process:', exc_info=e)
			sleep(5)
			continue

		if not q_items.actions:
			LOGGER.debug('No updates to process')
			sleep(POLLING_COOLDOWN)
			continue

		processed_event_ids = []
		errored_events = {}
		for i, (db_id, action_item) in enumerate(q_items.actions.items()):
			try:
				match action_item.type:
					case ActionType.DELETE_SOURCE_IDS:
						exec_in_proc(target=delete_by_source, args=(vectordb_loader, action_item.payload.sourceIds))

					case ActionType.DELETE_PROVIDER_ID:
						exec_in_proc(target=delete_by_provider, args=(vectordb_loader, action_item.payload.providerId))

					case ActionType.DELETE_USER_ID:
						exec_in_proc(target=delete_user, args=(vectordb_loader, action_item.payload.userId))

					case ActionType.UPDATE_ACCESS_SOURCE_ID:
						exec_in_proc(
							target=update_access,
							args=(
								vectordb_loader,
								action_item.payload.op,
								action_item.payload.userIds,
								action_item.payload.sourceId,
							),
						)

					case ActionType.UPDATE_ACCESS_PROVIDER_ID:
						exec_in_proc(
							target=update_access_provider,
							args=(
								vectordb_loader,
								action_item.payload.op,
								action_item.payload.userIds,
								action_item.payload.providerId,
							),
						)

					case ActionType.UPDATE_ACCESS_DECL_SOURCE_ID:
						exec_in_proc(
							target=decl_update_access,
							args=(
								vectordb_loader,
								action_item.payload.userIds,
								action_item.payload.sourceId,
							),
						)

					case _:
						LOGGER.warning(
							f'Unknown action type {action_item.type} for action id {db_id},'
							f' type {action_item.type}, skipping and marking as processed',
							extra={ 'action_item': action_item },
						)
						continue

				processed_event_ids.append(db_id)
			except SafeDbException as e:
				LOGGER.debug(
					f'Safe DB error thrown while processing action id {db_id}, type {action_item.type},'
					" it's safe to ignore and mark as processed.",
					exc_info=e,
					extra={ 'action_item': action_item },
				)
				processed_event_ids.append(db_id)
				continue

			except (LoaderException, DbException) as e:
				LOGGER.error(
					f'Error deleting source for action id {db_id}, type {action_item.type}: {e}',
					exc_info=e,
					extra={ 'action_item': action_item },
				)
				errored_events[db_id] = str(e)
				continue

			except Exception as e:
				LOGGER.error(
					f'Unexpected error processing action id {db_id}, type {action_item.type}: {e}',
					exc_info=e,
					extra={ 'action_item': action_item },
				)
				errored_events[db_id] = f'Unexpected error: {e}'
				continue

			if (i + 1) % 20 == 0:
				LOGGER.debug(f'Processed {i + 1} updates, sleeping for a bit to allow other operations to proceed')
				sleep(2)

		LOGGER.info(f'Processed {len(processed_event_ids)} updates with {len(errored_events)} errors', extra={
			'errored_events': errored_events,
		})

		if len(processed_event_ids) == 0:
			LOGGER.debug('No updates processed, skipping reporting to the server')
			continue

		try:
			nc.ocs(
				'DELETE',
				'/ocs/v2.php/apps/context_chat/queues/actions/',
				json={ 'actions': processed_event_ids },
			)
		except (
			niquests.exceptions.ConnectionError,
			niquests.exceptions.Timeout,
		) as e:
			LOGGER.info('Temporary error reporting processed updates, will retry:', exc_info=e)
			sleep(5)
			with suppress(Exception):
				nc = NextcloudApp()
				nc.ocs(
					'DELETE',
					'/ocs/v2.php/apps/context_chat/queues/actions/',
					json={ 'ids': processed_event_ids },
				)
			continue
		except Exception as e:
			LOGGER.exception('Error reporting processed updates:', exc_info=e)
			sleep(5)
			continue


def resolve_scope_list(source_ids: list[str], userId: str) -> list[str]:
	"""

	Parameters
	----------
	source_ids

	Returns
	-------
	source_ids with only files, no folders (or source_ids in case of non-file provider)
	"""
	nc = NextcloudApp()
	data = nc.ocs('POST', '/ocs/v2.php/apps/context_chat/resolve_scope_list', json={
		'source_ids': source_ids,
		'userId': userId,
	})
	return ScopeList.model_validate(data).source_ids


def request_processing_thread(app_config: TConfig, app_enabled: Event) -> None:
	LOGGER.info('Starting task fetcher loop')

	try:
		vectordb_loader = VectorDBLoader(app_config)
		llm_loader = LLMModelLoader(app_config)
	except LoaderException as e:
		LOGGER.error('Error initializing vector DB loader, files indexing thread will not start:', exc_info=e)
		return

	nc = NextcloudApp()
	llm: LLM = llm_loader.load()

	while True:
		if not __check_em_server(app_config):
			sleep(POLLING_COOLDOWN)
			continue

		if THREAD_STOP_EVENT.is_set():
			LOGGER.info('Updates processing thread is stopping due to stop event being set')
			return

		try:
			# Fetch pending task
			try:
				response = nc.providers.task_processing.next_task(
					['context_chat-context_chat', 'context_chat-context_chat_search'],
					['context_chat:context_chat', 'context_chat:context_chat_search'],
				)
				if not response:
					wait_for_tasks()
					continue
			except (NextcloudException, RequestException, JSONDecodeError) as e:
				LOGGER.error(f"Network error fetching the next task {e}", exc_info=e)
				wait_for_tasks(CHECK_INTERVAL_ON_ERROR)
				continue

			# Process task
			task = response["task"]
			userId = task['userId']

			try:
				LOGGER.debug(f'Processing task {task["id"]}')

				if task['input'].get('scopeType') == 'source':
					# Resolve scope list to only files, no folders
					task['input']['scopeList'] = resolve_scope_list(task['input'].get('scopeList'), userId)

				if task['type'] == 'context_chat:context_chat':
					result: LLMOutput = process_normal_task(task, vectordb_loader, llm, app_config)
					# Return result to Nextcloud
					success = return_normal_result_to_nextcloud(task['id'], userId, result)
				elif task['type'] == 'context_chat:context_chat_search':
					search_result: list[SearchResult] = process_search_task(task, vectordb_loader)
					# Return result to Nextcloud
					success = return_search_result_to_nextcloud(task['id'], userId, search_result)
				else:
					LOGGER.error(f'Unknown task type {task["type"]}')
					success = return_error_to_nextcloud(task['id'], Exception(f'Unknown task type {task["type"]}'))

				if success:
					LOGGER.info(f'Task {task["id"]} completed successfully')
				else:
					LOGGER.error(f'Failed to return result for task {task["id"]}')

			except ContextException as e:
				LOGGER.warning(f'Context error for task {task["id"]}: {e}')
				return_error_to_nextcloud(task['id'], e)
			except ValueError as e:
				LOGGER.warning(f'Validation error for task {task["id"]}: {e}')
				return_error_to_nextcloud(task['id'], e)
			except Exception as e:
				LOGGER.exception(f'Unexpected error processing task {task["id"]}', exc_info=e)
				return_error_to_nextcloud(task['id'], e)

		except Exception as e:
			LOGGER.exception('Error in task fetcher loop', exc_info=e)
			wait_for_tasks(CHECK_INTERVAL_ON_ERROR)

def trigger_handler(providerId: str):
	global TRIGGER
	print('TRIGGER called')
	TRIGGER.set()

def wait_for_tasks(interval = None):
	global TRIGGER
	global CHECK_INTERVAL
	global CHECK_INTERVAL_WITH_TRIGGER
	actual_interval = CHECK_INTERVAL if interval is None else interval
	if TRIGGER.wait(timeout=actual_interval):
		CHECK_INTERVAL = CHECK_INTERVAL_WITH_TRIGGER
	TRIGGER.clear()



def start_bg_threads(app_config: TConfig, app_enabled: Event):
	if APP_ROLE == AppRole.INDEXING or APP_ROLE == AppRole.NORMAL:
		if (
			ThreadType.FILES_INDEXING in THREADS
			or ThreadType.UPDATES_PROCESSING in THREADS
		):
			LOGGER.info('Background threads already running, skipping start')
			return

		THREAD_STOP_EVENT.clear()
		THREADS[ThreadType.FILES_INDEXING] = Thread(
			target=files_indexing_thread,
			args=(app_config, app_enabled),
			name='FilesIndexingThread',
		)
		THREADS[ThreadType.UPDATES_PROCESSING] = Thread(
			target=updates_processing_thread,
			args=(app_config, app_enabled),
			name='UpdatesProcessingThread',
		)
		THREADS[ThreadType.FILES_INDEXING].start()
		THREADS[ThreadType.UPDATES_PROCESSING].start()

	if APP_ROLE == AppRole.RP or APP_ROLE == AppRole.NORMAL:
		if ThreadType.REQUEST_PROCESSING in THREADS:
			LOGGER.info('Background threads already running, skipping start')
			return

		THREAD_STOP_EVENT.clear()
		THREADS[ThreadType.REQUEST_PROCESSING] = Thread(
			target=request_processing_thread,
			args=(app_config, app_enabled),
			name='RequestProcessingThread',
		)
		THREADS[ThreadType.REQUEST_PROCESSING].start()


def wait_for_bg_threads():
	if APP_ROLE == AppRole.INDEXING or APP_ROLE == AppRole.NORMAL:
		if (ThreadType.FILES_INDEXING not in THREADS or ThreadType.UPDATES_PROCESSING not in THREADS):
			return

		THREAD_STOP_EVENT.set()
		THREADS[ThreadType.FILES_INDEXING].join()
		THREADS[ThreadType.UPDATES_PROCESSING].join()
		THREADS.pop(ThreadType.FILES_INDEXING)
		THREADS.pop(ThreadType.UPDATES_PROCESSING)

	if APP_ROLE == AppRole.RP or APP_ROLE == AppRole.NORMAL:
		if (ThreadType.REQUEST_PROCESSING not in THREADS):
			return

		THREAD_STOP_EVENT.set()
		THREADS[ThreadType.REQUEST_PROCESSING].join()
		THREADS.pop(ThreadType.REQUEST_PROCESSING)


def query_vector_database(
	user_id: str,
	query: str,
	vectordb: BaseVectorDB,
	ctx_limit: int,
	scope_type: ScopeType | None = None,
	scope_list: list[str] | None = None,
) -> list[Document]:
	"""
	Query the vector database to retrieve relevant documents.

	Args:
		user_id: User ID for scoping the search
		query: The search query text
		vectordb: Vector database instance
		ctx_limit: Maximum number of documents to return
		scope_type: Optional scope type (PROVIDER or SOURCE)
		scope_list: Optional list of scope identifiers

	Returns:
		List of relevant Document objects

	Raises:
		ContextException: If scope type is provided without scope list
	"""
	context_docs = get_context_docs(user_id, query, vectordb, ctx_limit, scope_type, scope_list)
	LOGGER.debug('Retrieved context documents', extra={
		'user_id': user_id,
		'num_docs': len(context_docs),
		'ctx_limit': ctx_limit,
	})
	return context_docs


def prepare_context_chunks(context_docs: list[Document]) -> list[str]:
	"""
	Extract and format text chunks from documents for LLM context.

	Args:
		context_docs: List of Document objects from vector DB

	Returns:
		List of formatted text chunks including titles and content
	"""
	return get_context_chunks(context_docs)


def generate_llm_response(
	llm: LLM,
	app_config: TConfig,
	user_id: str,
	query: str,
	template: str,
	context_chunks: list[str],
	end_separator: str = '',
) -> str:
	"""
	Generate LLM response using the pruned query and context.

	Args:
		llm: Language model instance
		app_config: Application configuration
		user_id: User ID for the request
		query: The original query text
		template: Template for formatting the prompt
		context_chunks: Context chunks to include in the prompt
		end_separator: Optional separator to stop generation

	Returns:
		Generated LLM output text

	Raises:
		ValueError: If context length is too small to fit the query
	"""
	pruned_query_text = get_pruned_query(llm, app_config, query, template, context_chunks)

	stop = [end_separator] if end_separator else None
	output = llm.invoke(
		pruned_query_text,
		stop=stop,
		userid=user_id,
	).strip()

	LOGGER.debug('Generated LLM response', extra={
		'user_id': user_id,
		'output_length': len(output),
	})
	return output


def extract_unique_sources(context_docs: list[Document]) -> list[str]:
	"""
	Extract unique source IDs from context documents.

	Args:
		context_docs: List of Document objects

	Returns:
		List of unique source IDs
	"""
	unique_sources: list[str] = list({
		source for d in context_docs if (source := d.metadata.get('source'))
	})
	return unique_sources

def return_normal_result_to_nextcloud(task_id: int, userId: str, result: LLMOutput) -> bool:
	"""
	Return query result back to Nextcloud.

	Args:
		task_id: Unique task identifier
		result: The LLMOutput result to return

	Returns:
		True if successful, False otherwise
	"""
	LOGGER.debug('Returning result to Nextcloud', extra={
		'task_id': task_id,
		'output_length': len(result['output']),
		'num_sources': len(result['sources']),
	})

	nc = NextcloudApp()

	try:
		nc.providers.task_processing.report_result(task_id, {
			'output': result['output'],
			'sources': enrich_sources(result['sources'], userId),
		})
	except (NextcloudException, RequestException, JSONDecodeError) as e:
		LOGGER.error(f"Network error reporting task result {e}", exc_info=e)
		return False

	return True


def enrich_sources(results: list[SearchResult], userId: str) -> list[str]:
	nc = NextcloudApp()
	data = nc.ocs('POST', '/ocs/v2.php/apps/context_chat/enrich_sources', json={'sources': results, 'userId': userId})
	sources = EnrichedSourceList.model_validate(data).sources
	return [s.model_dump_json() for s in sources]


def return_search_result_to_nextcloud(task_id: int, userId: str, result: list[SearchResult]) -> bool:
	"""
	Return search result back to Nextcloud.

	Args:
		task_id: Unique task identifier
		result: The list of search results to return

	Returns:
		True if successful, False otherwise
	"""
	LOGGER.debug('Returning search result to Nextcloud', extra={
		'task_id': task_id,
		'num_sources': len(result),
	})

	nc = NextcloudApp()

	try:
		nc.providers.task_processing.report_result(task_id, {
			'sources': enrich_sources(result, userId),
		})
	except (NextcloudException, RequestException, JSONDecodeError) as e:
		LOGGER.error(f"Network error reporting search task result {e}", exc_info=e)
		return False

	return True

def return_error_to_nextcloud(task_id: int, e: Exception) -> bool:
	"""
	Return error result back to Nextcloud.

	Args:
		task_id: Unique task identifier
		e: error object

	Returns:
		True if successful, False otherwise
	"""
	LOGGER.debug('Returning error to Nextcloud', exc_info=e)

	nc = NextcloudApp()

	if isinstance(e, ValueError):
		message = "Validation error: " + str(e)
	elif isinstance(e, ContextException):
		message = "Context error" + str(e)
	else:
		message = "Unexpected error" + str(e)

	try:
		nc.providers.task_processing.report_result(task_id, None, message)
	except (NextcloudException, RequestException, JSONDecodeError) as e:
		LOGGER.error(f"Network error reporting task result {e}", exc_info=e)
		return False

	return True


def process_normal_task(
	task: dict[str, Any],
	vectordb_loader: VectorDBLoader,
	llm: LLM,
	app_config: TConfig,
) -> LLMOutput:
	"""
	Process a single query task.

	Args:
		task: Task dictionary from fetch_query_tasks_from_nextcloud
		vectordb_loader: Vector database loader instance
		llm: Language model instance
		app_config: Application configuration

	Returns:
		LLMOutput with generated text and sources

	Raises:
		Various exceptions from query execution
	"""
	user_id = task['userId']
	task_input = task['input']
	if task_input.get('scopeType') == 'none':
		task_input['scopeType'] = None

	return exec_in_proc(target=process_context_query,
		args=(
			user_id,
			vectordb_loader,
			llm,
			app_config,
			task_input.get('prompt'),
			CONTEXT_LIMIT,
			task_input.get('scopeType'),
			task_input.get('scopeList'),
		)
	)

def process_search_task(
	task: dict[str, Any],
	vectordb_loader: VectorDBLoader,
) -> list[SearchResult]:
	"""
	Process a single search task.

	Args:
		task: Task dictionary from fetch_query_tasks_from_nextcloud
		vectordb_loader: Vector database loader instance

	Returns:
		list of Search results

	Raises:
		Various exceptions from query execution
	"""
	user_id = task['userId']
	task_input = task['input']
	if task_input.get('scopeType') == 'none':
		task_input['scopeType'] = None

	return exec_in_proc(target=do_doc_search,
		args=(
			user_id,
			task_input.get('prompt'),
			vectordb_loader,
			CONTEXT_LIMIT,
			task_input.get('scopeType'),
			task_input.get('scopeList'),
		)
	)


def __check_em_server(app_config: TConfig) -> bool:
	embedding_model = NetworkEmbeddings(app_config=app_config)
	return embedding_model.check_connection()
