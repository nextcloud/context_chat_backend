import re

from fastapi.datastructures import UploadFile
from langchain.schema import Document

from ...dyn_loader import VectorDBLoader
from ...types import TConfig
from ...utils import is_valid_source_id, to_int
from ...vectordb.base import BaseVectorDB
from ...vectordb.types import DbException
from ..types import InDocument
from .doc_loader import decode_source
from .doc_splitter import get_splitter_for
from .mimetype_list import SUPPORTED_MIMETYPES


def _allowed_file(file: UploadFile) -> bool:
	return file.headers['type'] in SUPPORTED_MIMETYPES


def _filter_sources(
	vectordb: BaseVectorDB,
	sources: list[UploadFile]
) -> list[UploadFile]:
	'''
	Returns a filtered list of sources that are not already in the vectordb
	or have been modified since they were last added.
	It also deletes the old documents to prevent duplicates.

	Raises
	------
	DbException
	'''

	try:
		new_sources = vectordb.sources_to_embed(sources)
	except Exception as e:
		raise DbException('Error: Vectordb sources_to_embed error') from e

	return [
		source for source in sources
		if source.filename in new_sources
	]


def _sources_to_indocuments(config: TConfig, sources: list[UploadFile]) -> list[InDocument]:
	indocuments = []

	for source in sources:
		print('processing source:', source.filename, flush=True)

		# transform the source to have text data
		content = decode_source(source)

		if content is None or content == '':
			print('decoded empty source:', source.filename, flush=True)
			continue

		# replace more than two newlines with two newlines (also blank spaces, more than 4)
		content = re.sub(r'((\r)?\n){3,}', '\n\n', content)
		# NOTE: do not use this with all docs when programming files are added
		content = re.sub(r'(\s){5,}', r'\g<1>', content)
		# filter out null bytes
		content = content.replace('\0', '')

		if content is None or content == '':
			print('decoded empty source after cleanup:', source.filename, flush=True)
			continue

		print('decoded non empty source:', source.filename, flush=True)

		metadata = {
			'title': source.headers['title'],
			'type': source.headers['type'],
		}
		doc = Document(page_content=content, metadata=metadata)

		splitter = get_splitter_for(config.embedding_chunk_size, source.headers['type'])
		split_docs = splitter.split_documents([doc])

		indocuments.append(InDocument(
			documents=split_docs,
			userIds=source.headers['userIds'].split(','),
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
	filtered_sources = _filter_sources(vectordb, sources)

	if len(filtered_sources) == 0:
		# no new sources to embed
		print('Filtered all sources, nothing to embed', flush=True)
		return []

	print('Filtered sources:', [source.filename for source in filtered_sources], flush=True)
	indocuments = _sources_to_indocuments(config, filtered_sources)

	print('Converted sources to documents')

	if len(indocuments) == 0:
		# document(s) were empty, not an error
		print('All documents were found empty after being processed', flush=True)
		return []

	added_sources = vectordb.add_indocuments(indocuments)
	print('Added documents to vectordb', flush=True)
	return added_sources


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

	print(
		'Embedding sources:\n' +
		'\n'.join([f'{source.filename} ({source.headers["title"]})' for source in sources_filtered]),
		flush=True,
	)

	vectordb = vectordb_loader.load()
	return _process_sources(vectordb, config, sources_filtered)
