#
# SPDX-FileCopyrightText: 2026 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#

import logging
import os
from collections.abc import Mapping
from contextlib import suppress
from enum import Enum
from threading import Event, Thread
from time import sleep

import niquests
from nc_py_api import NextcloudApp
from pydantic import ValidationError

from .chain.ingest.injest import embed_sources
from .dyn_loader import VectorDBLoader
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
from .utils import exec_in_proc, get_app_role
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
MIN_FILES_PER_CPU = 4
# divides the batch into these many chunks
PARALLEL_FILE_PARSING = max(1, (os.cpu_count() or 2) - 1)  # todo: config?
ACTIONS_BATCH_SIZE = 512  # todo: config?
POLLING_COOLDOWN = 30


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

	def _load_sources(source_items: Mapping[int, SourceItem | ReceivedFileItem]) -> Mapping[int, IndexingError | None]:
		try:
			return exec_in_proc(
				target=embed_sources,
				args=(vectordb_loader, app_config, source_items),
			)
		except (DbException, EmbeddingException):
			raise
		except Exception as e:
			raise DbException('Error: failed to load sources') from e


	while True:
		if THREAD_STOP_EVENT.is_set():
			LOGGER.info('Files indexing thread is stopping due to stop event being set')
			return

		try:
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
			chunk_size = max(MIN_FILES_PER_CPU, FILES_INDEXING_BATCH_SIZE // PARALLEL_FILE_PARSING)

			# todo: do it in asyncio, it's not truly parallel yet
			# chunk file parsing for better file operation parallelism
			for i in range(0, len(q_items.files), chunk_size):
				chunk = dict(list(q_items.files.items())[i:i+chunk_size])
				files_result.update(_load_sources(chunk))

			for i in range(0, len(q_items.content_providers), chunk_size):
				chunk = dict(list(q_items.content_providers.items())[i:i+chunk_size])
				providers_result.update(_load_sources(chunk))

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


def request_processing_thread(app_config: TConfig, app_enabled: Event) -> None:
	...


def start_bg_threads(app_config: TConfig, app_enabled: Event):
	match APP_ROLE:
		case AppRole.INDEXING | AppRole.NORMAL:
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

		case AppRole.RP | AppRole.NORMAL:
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
	match APP_ROLE:
		case AppRole.INDEXING | AppRole.NORMAL:
			if (ThreadType.FILES_INDEXING not in THREADS or ThreadType.UPDATES_PROCESSING not in THREADS):
				return

			THREAD_STOP_EVENT.set()
			THREADS[ThreadType.FILES_INDEXING].join()
			THREADS[ThreadType.UPDATES_PROCESSING].join()
			THREADS.pop(ThreadType.FILES_INDEXING)
			THREADS.pop(ThreadType.UPDATES_PROCESSING)

		case AppRole.RP | AppRole.NORMAL:
			if (ThreadType.REQUEST_PROCESSING not in THREADS):
				return

			THREAD_STOP_EVENT.set()
			THREADS[ThreadType.REQUEST_PROCESSING].join()
			THREADS.pop(ThreadType.REQUEST_PROCESSING)
