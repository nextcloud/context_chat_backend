#
# SPDX-FileCopyrightText: 2026 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#

import asyncio
import logging
import os
from contextlib import suppress
from enum import Enum
from io import BytesIO
from threading import Event, Thread
from time import sleep

import niquests
from nc_py_api import AsyncNextcloudApp, NextcloudApp
from pydantic import ValidationError

from .chain.ingest.injest import embed_sources
from .dyn_loader import VectorDBLoader
from .types import (
	AppRole,
	EmbeddingException,
	FilesQueueItem,
	IndexingError,
	IndexingException,
	LoaderException,
	ReceivedFileItem,
	SourceItem,
	TConfig,
)
from .utils import exec_in_proc, get_app_role
from .vectordb.types import DbException

APP_ROLE = get_app_role()
THREADS = {}
LOGGER = logging.getLogger('ccb.task_fetcher')
FILES_INDEXING_BATCH_SIZE = 64  # todo: config?
# divides the batch into these many chunks
PARALLEL_FILE_PARSING = max(1, (os.cpu_count() or 2) - 1)  # todo: config?
# max concurrent fetches to avoid overloading the NC server or hitting rate limits
CONCURRENT_FILE_FETCHES = 10  # todo: config?
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB, todo: config?


class ThreadType(Enum):
	FILES_INDEXING = 'files_indexing'
	UPDATES_PROCESSING = 'updates_processing'
	REQUEST_PROCESSING = 'request_processing'


async def __fetch_file_content(
	semaphore: asyncio.Semaphore,
	file_id: int,
	user_id: str,
	_rlimit = 3,
) -> BytesIO:
	'''
	Raises
	------
	IndexingException
	'''

	async with semaphore:
		nc = AsyncNextcloudApp()
		try:
			# a file pointer for storing the stream in memory until it is consumed
			fp = BytesIO()
			await nc._session.download2fp(
				url_path=f'/apps/context_chat/files/{file_id}',
				fp=fp,
				dav=False,
				params={ 'userId': user_id },
			)
			return fp
		except niquests.exceptions.RequestException as e:
			# todo: raise IndexingException with retryable=True for rate limit errors,
			# todo: and handle it in the caller to not delete the source from the queue and retry later through
			# todo: the normal lock expiry mechanism
			if e.response is None:
				raise

			if e.response.status_code == niquests.codes.too_many_requests:  # pyright: ignore[reportAttributeAccessIssue]
				# todo: implement rate limits in php CC?
				wait_for = int(e.response.headers.get('Retry-After', '30'))
				if _rlimit <= 0:
					raise IndexingException(
						f'Rate limited when fetching content for file id {file_id}, user id {user_id},'
						' max retries exceeded',
						retryable=True,
					) from e
				LOGGER.warning(
					f'Rate limited when fetching content for file id {file_id}, user id {user_id},'
					f' waiting {wait_for} before retrying',
					exc_info=e,
				)
				await asyncio.sleep(wait_for)
				return await __fetch_file_content(semaphore, file_id, user_id, _rlimit - 1)

			raise
		except IndexingException:
			raise
		except Exception as e:
			LOGGER.error(f'Error fetching content for file id {file_id}, user id {user_id}: {e}', exc_info=e)
			raise IndexingException(f'Error fetching content for file id {file_id}, user id {user_id}: {e}') from e


async def __fetch_files_content(
	files: dict[int, ReceivedFileItem]
) -> dict[int, SourceItem | IndexingError]:
	source_items = {}
	semaphore = asyncio.Semaphore(CONCURRENT_FILE_FETCHES)
	tasks = []

	for file_id, file_item in files.items():
		if file_item.size > MAX_FILE_SIZE:
			LOGGER.info(
				f'Skipping file id {file_id}, source id {file_item.reference} due to size'
				f' {(file_item.size/(1024*1024)):.2f} MiB exceeding the limit {(MAX_FILE_SIZE/(1024*1024)):.2f} MiB',
			)
			source_items[file_id] = IndexingError(
				error=(
					f'File size {(file_item.size/(1024*1024)):.2f} MiB'
					f' exceeds the limit {(MAX_FILE_SIZE/(1024*1024)):.2f} MiB'
				),
				retryable=False,
			)
			continue
		# todo: perform the existing file check before fetching the content to avoid unnecessary fetches
		# any user id from the list should have read access to the file
		tasks.append(asyncio.ensure_future(__fetch_file_content(semaphore, file_id, file_item.userIds[0])))

	results = await asyncio.gather(*tasks, return_exceptions=True)
	for (file_id, file_item), result in zip(files.items(), results, strict=True):
		if isinstance(result, IndexingException):
			LOGGER.error(
				f'Error fetching content for file id {file_id}, reference {file_item.reference}: {result}',
				exc_info=result,
			)
			source_items[file_id] = IndexingError(
				error=str(result),
				retryable=result.retryable,
			)
		elif isinstance(result, str) or isinstance(result, BytesIO):
			source_items[file_id] = SourceItem(
				**file_item.model_dump(),
				content=result,
			)
		elif isinstance(result, BaseException):
			LOGGER.error(
				f'Unexpected error fetching content for file id {file_id}, reference {file_item.reference}: {result}',
				exc_info=result,
			)
			source_items[file_id] = IndexingError(
				error=f'Unexpected error: {result}',
				retryable=True,
			)
		else:
			LOGGER.error(
				f'Unknown error fetching content for file id {file_id}, reference {file_item.reference}: {result}',
				exc_info=True,
			)
			source_items[file_id] = IndexingError(
				error='Unknown error',
				retryable=True,
			)
	return source_items


def files_indexing_thread(app_config: TConfig, app_enabled: Event) -> None:
	try:
		vectordb_loader = VectorDBLoader(app_config)
	except LoaderException as e:
		LOGGER.error('Error initializing vector DB loader, files indexing thread will not start:', exc_info=e)
		return

	def _load_sources(source_items: dict[int, SourceItem]) -> dict[int, IndexingError | None]:
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
		if not app_enabled.is_set():
			LOGGER.info('Files indexing thread is stopping as the app is disabled')
			return

		try:
			nc = NextcloudApp()
			# todo: add the 'size' param to the return of this call.
			q_items_res = nc.ocs(
				'GET',
				'/apps/context_chat/queues/documents',
				params={ 'n': FILES_INDEXING_BATCH_SIZE }
			)

			try:
				q_items = FilesQueueItem.model_validate(q_items_res)
			except ValidationError as e:
				raise Exception(f'Error validating queue items response: {e}\nResponse content: {q_items_res}') from e

			# populate files content and convert to source items
			fetched_files = {}
			source_files = {}
			# unified error structure for files and content providers
			source_errors = {}

			if q_items.files:
				fetched_files = asyncio.run(__fetch_files_content(q_items.files))

			for file_id, result in fetched_files.items():
				if isinstance(result, SourceItem):
					source_files[file_id] = result
				else:
					source_errors[file_id] = result

			files_result = {}
			providers_result = {}
			chunk_size = FILES_INDEXING_BATCH_SIZE // PARALLEL_FILE_PARSING

			# chunk file parsing for better file operation parallelism
			for i in range(0, len(source_files), chunk_size):
				chunk = dict(list(source_files.items())[i:i+chunk_size])
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
						file_id: error
						for file_id, error in files_result.items()
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
		to_delete_file_ids = [
			file_id for file_id, result in files_result.items()
			if result is None or (isinstance(result, IndexingError) and not result.retryable)
		]
		to_delete_provider_ids = [
			provider_id for provider_id, result in providers_result.items()
			if result is None or (isinstance(result, IndexingError) and not result.retryable)
		]

		try:
			nc.ocs(
				'DELETE',
				'/apps/context_chat/queues/documents/',
				json={
					'files': to_delete_file_ids,
					'content_providers': to_delete_provider_ids,
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
					'/apps/context_chat/queues/documents/',
					json={
						'files': to_delete_file_ids,
						'content_providers': to_delete_provider_ids,
					},
				)
			continue
		except Exception as e:
			LOGGER.exception('Error reporting indexing results:', exc_info=e)
			sleep(5)
			continue



def updates_processing_thread(app_config: TConfig, app_enabled: Event) -> None:
	...


def request_processing_thread(app_config: TConfig, app_enabled: Event) -> None:
	...


def start_bg_threads(app_config: TConfig, app_enabled: Event):
	match APP_ROLE:
		case AppRole.INDEXING | AppRole.NORMAL:
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
			THREADS[ThreadType.FILES_INDEXING].join()
			THREADS[ThreadType.UPDATES_PROCESSING].join()
			THREADS.pop(ThreadType.FILES_INDEXING)
			THREADS.pop(ThreadType.UPDATES_PROCESSING)
		case AppRole.RP | AppRole.NORMAL:
			if (ThreadType.REQUEST_PROCESSING not in THREADS):
				return
			THREADS[ThreadType.REQUEST_PROCESSING].join()
			THREADS.pop(ThreadType.REQUEST_PROCESSING)
