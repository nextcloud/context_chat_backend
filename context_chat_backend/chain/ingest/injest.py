#
# SPDX-FileCopyrightText: 2023 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
import logging
import re

from langchain.schema import Document

from ...dyn_loader import VectorDBLoader
from ...types import IndexingError, SourceItem, TConfig
from ...vectordb.base import BaseVectorDB
from ...vectordb.types import DbException, SafeDbException, UpdateAccessOp
from ..types import InDocument
from .doc_loader import decode_source
from .doc_splitter import get_splitter_for

logger = logging.getLogger('ccb.injest')


def _filter_sources(
	vectordb: BaseVectorDB,
	sources: dict[int, SourceItem]
) -> tuple[dict[int, SourceItem], dict[int, SourceItem]]:
	'''
	Returns
	-------
	tuple[list[str], list[UploadFile]]
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
	sources: dict[int, SourceItem]
) -> tuple[dict[int, InDocument], dict[int, IndexingError]]:
	indocuments = {}
	errored_docs = {}

	for db_id, source in sources.items():
		logger.debug('processing source', extra={ 'source_id': source.reference })

		# todo: maybe fetch the content of the files here
		# transform the source to have text data
		content = decode_source(source)

		if content is None or (content := content.strip()) == '':
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
		content = content.replace('\0', '')

		if content is None or content == '':
			logger.debug('decoded empty source after cleanup', extra={ 'source_id': source.reference })
			errored_docs[db_id] = IndexingError(
				error='Decoded content is empty',
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
	existing_sources: dict[int, SourceItem]
) -> dict[int, IndexingError | None]:
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
	sources: dict[int, SourceItem]
) -> dict[int, IndexingError | None]:
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

	if len(to_embed_sources) == 0:
		# no new sources to embed
		logger.debug('Filtered all sources, nothing to embed')
		return source_proc_results

	logger.debug('Filtered sources:', extra={
		'source_ids': [source.reference for source in to_embed_sources.values()]
	})
	# invalid/empty sources are filtered out here and not counted in loaded/retryable
	indocuments, errored_docs = _sources_to_indocuments(config, to_embed_sources)

	source_proc_results.update(errored_docs)
	logger.debug('Converted sources to documents')

	if len(indocuments) == 0:
		# filtered document(s) were invalid/empty, not an error
		logger.debug('All documents were found empty after being processed')
		return source_proc_results

	doc_add_results = vectordb.add_indocuments(indocuments)
	source_proc_results.update(doc_add_results)
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
	sources: dict[int, SourceItem]
) -> dict[int, IndexingError | None]:
	logger.debug('Embedding sources:', extra={
		'source_ids': [
			f'{source.reference} ({_decode_latin_1(source.title)})'
			for source in sources.values()
		],
		'len(source_ids)': len(sources),
	})

	vectordb = vectordb_loader.load()
	return _process_sources(vectordb, config, sources)
