#
# SPDX-FileCopyrightText: 2023 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
import asyncio
import logging
import re
from collections.abc import Mapping
from io import BytesIO

import niquests
from langchain.schema import Document
from nc_py_api import AsyncNextcloudApp

from ...dyn_loader import VectorDBLoader
from ...types import IndexingError, IndexingException, ReceivedFileItem, SourceItem, TConfig
from ...vectordb.base import BaseVectorDB
from ...vectordb.types import DbException, SafeDbException, UpdateAccessOp
from ..types import InDocument
from .doc_loader import decode_source
from .doc_splitter import get_splitter_for

logger = logging.getLogger('ccb.injest')

# max concurrent fetches to avoid overloading the NC server or hitting rate limits
CONCURRENT_FILE_FETCHES = 10  # todo: config?
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB, all loaded in RAM at once, todo: config?


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
				url_path=f'/ocs/v2.php/apps/context_chat/files/{file_id}',
				fp=fp,
				dav=False,
				params={ 'userId': user_id },
			)
			fp.seek(0)
			return fp
		except niquests.exceptions.RequestException as e:
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
				logger.warning(
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
			logger.error(f'Error fetching content for file id {file_id}, user id {user_id}: {e}', exc_info=e)
			raise IndexingException(f'Error fetching content for file id {file_id}, user id {user_id}: {e}') from e


async def __fetch_files_content(
	sources: Mapping[int, SourceItem | ReceivedFileItem]
) -> tuple[Mapping[int, SourceItem], Mapping[int, IndexingError]]:
	source_items = {}
	error_items = {}
	semaphore = asyncio.Semaphore(CONCURRENT_FILE_FETCHES)
	tasks = []

	for db_id, file in sources.items():
		if isinstance(file, SourceItem):
			continue

		try:
			# to detect any validation errors but it should not happen since file.reference is validated
			file.file_id  # noqa: B018
		except ValueError as e:
			logger.error(
				f'Invalid file reference format for db id {db_id}, file reference {file.reference}: {e}',
				exc_info=e,
			)
			error_items[db_id] = IndexingError(
				error=f'Invalid file reference format: {file.reference}',
				retryable=False,
			)
			continue

		if file.size > MAX_FILE_SIZE:
			logger.info(
				f'Skipping db id {db_id}, file id {file.file_id}, source id {file.reference} due to size'
				f' {(file.size/(1024*1024)):.2f} MiB exceeding the limit {(MAX_FILE_SIZE/(1024*1024)):.2f} MiB',
			)
			error_items[db_id] = IndexingError(
				error=(
					f'File size {(file.size/(1024*1024)):.2f} MiB'
					f' exceeds the limit {(MAX_FILE_SIZE/(1024*1024)):.2f} MiB'
				),
				retryable=False,
			)
			continue
		# any user id from the list should have read access to the file
		tasks.append(asyncio.ensure_future(__fetch_file_content(semaphore, file.file_id, file.userIds[0])))

	results = await asyncio.gather(*tasks, return_exceptions=True)
	for (db_id, file), result in zip(sources.items(), results, strict=True):
		if isinstance(file, SourceItem):
			continue

		if isinstance(result, IndexingException):
			logger.error(
				f'Error fetching content for db id {db_id}, file id {file.file_id}, reference {file.reference}'
				f': {result}',
				exc_info=result,
			)
			error_items[db_id] = IndexingError(
				error=str(result),
				retryable=result.retryable,
			)
		elif isinstance(result, str) or isinstance(result, BytesIO):
			source_items[db_id] = SourceItem(
				**{
					**file.model_dump(),
					'content': result,
				}
			)
		elif isinstance(result, BaseException):
			logger.error(
				f'Unexpected error fetching content for db id {db_id}, file id {file.file_id},'
				f' reference {file.reference}: {result}',
				exc_info=result,
			)
			error_items[db_id] = IndexingError(
				error=f'Unexpected error: {result}',
				retryable=True,
			)
		else:
			logger.error(
				f'Unknown error fetching content for db id {db_id}, file id {file.file_id}, reference {file.reference}'
				f': {result}',
				exc_info=True,
			)
			error_items[db_id] = IndexingError(
				error='Unknown error',
				retryable=True,
			)

	# add the content providers from the orginal "sources" to the result unprocessed
	for db_id, source in sources.items():
		if isinstance(source, SourceItem):
			source_items[db_id] = source

	return source_items, error_items


def _filter_sources(
	vectordb: BaseVectorDB,
	sources: Mapping[int, SourceItem | ReceivedFileItem]
) -> tuple[Mapping[int, SourceItem | ReceivedFileItem], Mapping[int, SourceItem | ReceivedFileItem]]:
	'''
	Returns
	-------
	tuple[Mapping[int, SourceItem | ReceivedFileItem], Mapping[int, SourceItem | ReceivedFileItem]]:
		First value is a list of sources that already exist in the vectordb.
		Second value is a list of sources that are new and should be embedded.
	'''

	try:
		existing_source_ids, to_embed_source_ids = vectordb.check_sources(sources)
	except Exception as e:
		raise DbException('Error: Vectordb error while checking existing sources in indexing') from e

	existing_sources = {}
	to_embed_sources = {}

	for db_id, source in sources.items():
		if source.reference in existing_source_ids:
			existing_sources[db_id] = source
		elif source.reference in to_embed_source_ids:
			to_embed_sources[db_id] = source

	return existing_sources, to_embed_sources


def _sources_to_indocuments(
	config: TConfig,
	sources: Mapping[int, SourceItem]
) -> tuple[Mapping[int, InDocument], Mapping[int, IndexingError]]:
	indocuments = {}
	errored_docs = {}

	for db_id, source in sources.items():
		logger.debug('processing source', extra={ 'source_id': source.reference })

		# transform the source to have text data
		try:
			content = decode_source(source)
		except IndexingException as e:
			logger.error(f'Error decoding source ({source.reference}): {e}', exc_info=e)
			errored_docs[db_id] = IndexingError(
				error=str(e),
				retryable=False,
			)
			continue

		if content == '':
			logger.debug('decoded empty source', extra={ 'source_id': source.reference })
			errored_docs[db_id] = IndexingError(
				error='Decoded content is empty',
				retryable=False,
			)
			continue

		# replace more than two newlines with two newlines (also blank spaces, more than 4)
		content = re.sub(r'((\r)?\n){3,}', '\n\n', content)
		# NOTE: do not use this with all docs when programming files are added
		content = re.sub(r'(\s){5,}', r'\g<1>', content)
		# filter out null bytes
		content = content.replace('\0', '').strip()

		if content == '':
			logger.debug('decoded empty source after cleanup', extra={ 'source_id': source.reference })
			errored_docs[db_id] = IndexingError(
				error='Cleaned up content is empty',
				retryable=False,
			)
			continue

		logger.debug('decoded non empty source', extra={ 'source_id': source.reference })

		metadata = {
			'source': source.reference,
			'title': _decode_latin_1(source.title),
			'type': source.type,
		}
		doc = Document(page_content=content, metadata=metadata)

		splitter = get_splitter_for(config.embedding_chunk_size, source.type)
		split_docs = splitter.split_documents([doc])
		logger.debug('split document into chunks', extra={
			'source_id': source.reference,
			'len(split_docs)': len(split_docs),
		})

		indocuments[db_id] = InDocument(
			documents=split_docs,
			userIds=list(map(_decode_latin_1, source.userIds)),
			source_id=source.reference,
			provider=source.provider,
			modified=source.modified,  # pyright: ignore[reportArgumentType]
		)

	return indocuments, errored_docs


def _increase_access_for_existing_sources(
	vectordb: BaseVectorDB,
	existing_sources: Mapping[int, SourceItem | ReceivedFileItem]
) -> Mapping[int, IndexingError | None]:
	'''
	update userIds for existing sources
	allow the userIds as additional users, not as the only users
	'''
	if len(existing_sources) == 0:
		return {}

	results = {}
	logger.debug('Increasing access for existing sources', extra={
		'source_ids': [source.reference for source in existing_sources.values()]
	})
	for db_id, source in existing_sources.items():
		try:
			vectordb.update_access(
				UpdateAccessOp.ALLOW,
				list(map(_decode_latin_1, source.userIds)),
				source.reference,
			)
			results[db_id] = None
		except SafeDbException as e:
			logger.error(f'Failed to update access for source ({source.reference}): {e.args[0]}')
			results[db_id] = IndexingError(
				error=str(e),
				retryable=False,
			)
			continue
		except Exception as e:
			logger.error(f'Unexpected error while updating access for source ({source.reference}): {e}')
			results[db_id] = IndexingError(
				error='Unexpected error while updating access',
				retryable=True,
			)
			continue
	return results


def _process_sources(
	vectordb: BaseVectorDB,
	config: TConfig,
	sources: Mapping[int, SourceItem | ReceivedFileItem]
) -> Mapping[int, IndexingError | None]:
	'''
	Processes the sources and adds them to the vectordb.
	Returns the list of source ids that were successfully added and those that need to be retried.
	'''
	existing_sources, to_embed_sources = _filter_sources(vectordb, sources)
	logger.debug('db filter source results', extra={
		'len(existing_sources)': len(existing_sources),
		'existing_sources': existing_sources,
		'len(to_embed_sources)': len(to_embed_sources),
		'to_embed_sources': to_embed_sources,
	})

	source_proc_results = _increase_access_for_existing_sources(vectordb, existing_sources)

	populated_to_embed_sources, errored_sources = asyncio.run(__fetch_files_content(to_embed_sources))
	source_proc_results.update(errored_sources)  # pyright: ignore[reportAttributeAccessIssue]

	if len(populated_to_embed_sources) == 0:
		# no new sources to embed
		logger.debug('Filtered all sources, nothing to embed')
		return source_proc_results

	logger.debug('Filtered sources:', extra={
		'source_ids': [source.reference for source in populated_to_embed_sources.values()]
	})
	# invalid/empty sources are filtered out here and not counted in loaded/retryable
	indocuments, errored_docs = _sources_to_indocuments(config, populated_to_embed_sources)

	source_proc_results.update(errored_docs)  # pyright: ignore[reportAttributeAccessIssue]
	logger.debug('Converted sources to documents')

	if len(indocuments) == 0:
		# filtered document(s) were invalid/empty, not an error
		logger.debug('All documents were found empty after being processed')
		return source_proc_results

	logger.debug('Adding documents to vectordb', extra={
		'source_ids': [indoc.source_id for indoc in indocuments.values()]
	})

	doc_add_results = vectordb.add_indocuments(indocuments)
	source_proc_results.update(doc_add_results)  # pyright: ignore[reportAttributeAccessIssue]
	logger.debug('Added documents to vectordb')

	return source_proc_results


def _decode_latin_1(s: str) -> str:
	try:
		return s.encode('latin-1').decode('utf-8')
	except UnicodeDecodeError:
		logger.error('Failed to decode latin-1: %s', s)
		return s


def embed_sources(
	vectordb_loader: VectorDBLoader,
	config: TConfig,
	sources: Mapping[int, SourceItem | ReceivedFileItem]
) -> Mapping[int, IndexingError | None]:
	logger.debug('Embedding sources:', extra={
		'source_ids': [
			f'{source.reference} ({_decode_latin_1(source.title)})'
			for source in sources.values()
		],
		'len(source_ids)': len(sources),
	})

	vectordb = vectordb_loader.load()
	return _process_sources(vectordb, config, sources)
