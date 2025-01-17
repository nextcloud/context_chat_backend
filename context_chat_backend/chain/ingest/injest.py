#
# SPDX-FileCopyrightText: 2023 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
import logging
import re

from fastapi.datastructures import UploadFile
from langchain.schema import Document

from ...dyn_loader import VectorDBLoader
from ...types import TConfig
from ...utils import is_valid_source_id, to_int
from ...vectordb.base import BaseVectorDB
from ...vectordb.types import DbException, SafeDbException, UpdateAccessOp
from ..types import InDocument
from .doc_loader import decode_source
from .doc_splitter import get_splitter_for
from .mimetype_list import SUPPORTED_MIMETYPES

logger = logging.getLogger('ccb.injest')

def _allowed_file(file: UploadFile) -> bool:
	return file.headers['type'] in SUPPORTED_MIMETYPES


def _filter_sources(
	vectordb: BaseVectorDB,
	sources: list[UploadFile]
) -> tuple[list[UploadFile], list[UploadFile]]:
	'''
	Returns
	-------
	tuple[list[str], list[UploadFile]]
		First value is a list of sources that already exist in the vectordb.
		Second value is a list of sources that are new and should be embedded.
	'''

	try:
		existing_sources, new_sources = vectordb.check_sources(sources)
	except Exception as e:
		raise DbException('Error: Vectordb sources_to_embed error') from e

	return ([
		source for source in sources
		if source.filename in existing_sources
	], [
		source for source in sources
		if source.filename in new_sources
	])


def _sources_to_indocuments(config: TConfig, sources: list[UploadFile]) -> list[InDocument]:
	indocuments = []

	for source in sources:
		logger.debug('processing source', extra={ 'source_id': source.filename })

		# transform the source to have text data
		content = decode_source(source)

		if content is None or content == '':
			logger.debug('decoded empty source', extra={ 'source_id': source.filename })
			continue

		# replace more than two newlines with two newlines (also blank spaces, more than 4)
		content = re.sub(r'((\r)?\n){3,}', '\n\n', content)
		# NOTE: do not use this with all docs when programming files are added
		content = re.sub(r'(\s){5,}', r'\g<1>', content)
		# filter out null bytes
		content = content.replace('\0', '')

		if content is None or content == '':
			logger.debug('decoded empty source after cleanup', extra={ 'source_id': source.filename })
			continue

		logger.debug('decoded non empty source', extra={ 'source_id': source.filename })

		metadata = {
			'source': source.filename,
			'title': _decode_latin_1(source.headers['title']),
			'type': source.headers['type'],
		}
		doc = Document(page_content=content, metadata=metadata)

		splitter = get_splitter_for(config.embedding_chunk_size, source.headers['type'])
		split_docs = splitter.split_documents([doc])
		logger.debug('split document into chunks', extra={
			'source_id': source.filename,
			'len(split_docs)': len(split_docs),
		})

		indocuments.append(InDocument(
			documents=split_docs,
			userIds=list(map(_decode_latin_1, source.headers['userIds'].split(','))),
			source_id=source.filename,  # pyright: ignore[reportArgumentType]
			provider=source.headers['provider'],
			modified=to_int(source.headers['modified']),
		))

	return indocuments


def _process_sources(
	vectordb: BaseVectorDB,
	config: TConfig,
	sources: list[UploadFile],
) -> list[str]:
	'''
	Processes the sources and adds them to the vectordb.
	Returns the list of source ids that were successfully added.
	'''
	existing_sources, filtered_sources = _filter_sources(vectordb, sources)
	logger.debug('db filter source results', extra={
		'len(existing_sources)': len(existing_sources),
		'existing_sources': existing_sources,
		'len(filtered_sources)': len(filtered_sources),
		'filtered_sources': filtered_sources,
	})

	# update userIds for existing sources
	# allow the userIds as additional users, not as the only users
	if len(existing_sources) > 0:
		logger.debug('Increasing access for existing sources', extra={
			'source_ids': [source.filename for source in existing_sources]
		})
		for source in existing_sources:
			try:
				vectordb.update_access(
					UpdateAccessOp.allow,
					list(map(_decode_latin_1, source.headers['userIds'].split(','))),
					source.filename,  # pyright: ignore[reportArgumentType]
				)
			except SafeDbException as e:
				logger.error(f'Failed to update access for source ({source.filename}): {e.args[0]}')
				continue

	if len(filtered_sources) == 0:
		# no new sources to embed
		logger.debug('Filtered all sources, nothing to embed')
		return []

	logger.debug('Filtered sources:', extra={
		'source_ids': [source.filename for source in filtered_sources]
	})
	indocuments = _sources_to_indocuments(config, filtered_sources)

	logger.debug('Converted all sources to documents')

	if len(indocuments) == 0:
		# document(s) were empty, not an error
		logger.debug('All documents were found empty after being processed')
		return []

	added_sources = vectordb.add_indocuments(indocuments)
	logger.debug('Added documents to vectordb')
	return added_sources


def _decode_latin_1(s: str) -> str:
	try:
		return s.encode('latin-1').decode('utf-8')
	except UnicodeDecodeError:
		logger.error('Failed to decode latin-1: %s', s)
		return s


def embed_sources(
	vectordb_loader: VectorDBLoader,
	config: TConfig,
	sources: list[UploadFile],
) -> list[str]:
	# either not a file or a file that is allowed
	sources_filtered = [
		source for source in sources
		if is_valid_source_id(source.filename)  # pyright: ignore[reportArgumentType]
		or _allowed_file(source)
	]

	logger.debug('Embedding sources:', extra={
		'source_ids': [
			f'{source.filename} ({_decode_latin_1(source.headers["title"])})'
			for source in sources_filtered
		],
	})

	vectordb = vectordb_loader.load()
	return _process_sources(vectordb, config, sources_filtered)
