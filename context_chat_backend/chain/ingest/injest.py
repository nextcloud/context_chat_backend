import multiprocessing as mp
import re
import threading
from functools import partial
from logging import error as log_error

from fastapi.datastructures import UploadFile
from langchain.schema import Document

from ...config_parser import TConfig
from ...dyn_loader import VectorDBLoader
from ...utils import log, not_none, to_int
from ...vectordb import BaseVectorDB
from .doc_loader import decode_source
from .doc_splitter import get_splitter_for
from .mimetype_list import SUPPORTED_MIMETYPES

# embed_lock = threading.Lock()

def _allowed_file(file: UploadFile) -> bool:
	return file.headers.get('type', default='') in SUPPORTED_MIMETYPES


def _filter_sources(
	user_id: str,
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
	to_delete = {}

	input_sources = {}
	for source in sources:
		if not not_none(source.filename) or not not_none(source.headers.get('modified')):
			continue
		input_sources[source.filename] = source.headers.get('modified')

	existing_objects = vectordb.get_objects_from_metadata(
		user_id,
		'source',
		list(input_sources.keys())
	)

	for source, existing_meta in existing_objects.items():
		# recently modified files are re-embedded
		if to_int(input_sources.get(source)) > to_int(existing_meta.get('modified')):
			to_delete[source] = existing_meta.get('id')

	# delete old sources
	vectordb.delete_by_ids(user_id, list(to_delete.values()))

	# sources not already in the vectordb + the ones that were deleted
	new_sources = set(input_sources.keys()) \
		.difference(set(existing_objects))
	new_sources.update(set(to_delete.keys()))

	return [
		source for source in sources
		if source.filename in new_sources
	]


def _source_to_documents(embedding_chunk_size: int, source: UploadFile) -> tuple[str, list[Document]] | None:
	'''
	Converts a source to a set of documents, split into chunks and laced with metadata,
	and returns it with the user_id.
	'''
	log('in _source_to_documents, pid:', mp.current_process().pid)
	user_id = source.headers['userId']
	if user_id is None:
		log_error(f'userId not found in headers for source: {source.filename}')
		return None

	metadata = {
		'source': source.filename,
		'title': source.headers['title'],
		'type': source.headers['type'],
		'modified': source.headers['modified'],
		'provider': source.headers['provider'],
	}

	# transform the source to have text data
	content = decode_source(source)
	if content is None or content == '':
		return None

	log('in _source_to_documents, after decode_source, content:', content[:100])
	# replace more than two newlines with two newlines (also blank spaces, more than 4)
	content = re.sub(r'((\r)?\n){3,}', '\n\n', content)
	# NOTE: do not use this with all docs when programming files are added
	content = re.sub(r'(\s){5,}', r'\g<1>', content)
	# filter out null bytes
	content = content.replace('\0', '')

	text_splitter = get_splitter_for(embedding_chunk_size, metadata['type'])
	# split_documents instead of split_text to copy metadata to all documents and have start_index key
	split_documents = text_splitter.split_documents([Document(page_content=content, metadata=metadata)])
	# filter out empty documents
	split_documents = list(filter(lambda doc: doc.page_content != '', split_documents))

	if len(split_documents) == 0:
		return None

	return (user_id, split_documents)


'''#todo
def _bucket_by_userid(documents: list[tuple[str, list[Document]]]) -> dict[str, list[Document]]:
	bucketed_documents = {}

	for user_id, docs in documents:
		if bucketed_documents.get(user_id) is not None:
			bucketed_documents[user_id].extend(docs)
		else:
			bucketed_documents[user_id] = docs

	return bucketed_documents
'''

# todo: n procs
pool = mp.get_context('spawn').Pool(4, maxtasksperchild=10)

def _embed_document(config: TConfig, source: UploadFile) -> bool:
	vectordb = VectorDBLoader(config).load()
	result = _source_to_documents(config['embedding_chunk_size'], source)
	if result is None:
		return False

	user_id, split_documents = result
	user_client = vectordb.get_user_client(user_id)
	doc_ids = user_client.add_documents(split_documents)

	return len(split_documents) == len(doc_ids)


def _process_sources(config: TConfig, sources: list[UploadFile]) -> bool:
	vectordb = VectorDBLoader(config).load()
	filtered_sources = _filter_sources(sources[0].headers['userId'], vectordb, sources)

	if len(filtered_sources) == 0:
		# no new sources to embed
		print('Filtered all docs, no new sources to embed', flush=True)
		return True

	log('in _process_sources, before mp.Pool, pid:', mp.current_process().pid)
	# with mp.get_context('forkserver').Pool(config['doc_parser_workers'], maxtasksperchild=10) as pool:
	results = pool.map(partial(_embed_document, config), filtered_sources)

	if not any(results):
		print('All provided sources were empty', flush=True)
		return True

	return all(results)


def embed_sources(
	config: TConfig,
	sources: list[UploadFile],
) -> bool:
	# either not a file or a file that is allowed
	sources_filtered = [
		source for source in sources
		if (source.filename is not None and not source.filename.startswith('files__default: '))
		or _allowed_file(source)
	]

	print(
		'Embedding sources:\n' +
		'\n'.join([f'{source.filename} ({source.headers.get("title", "")})' for source in sources_filtered]),
		flush=True,
	)
	return _process_sources(config, sources_filtered)
