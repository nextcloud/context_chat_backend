import re
from logging import error as log_error

from fastapi.datastructures import UploadFile
from langchain.schema import Document

from ...utils import not_none, to_int
from ...vectordb import BaseVectorDB, DbException
from .doc_loader import decode_source
from .doc_splitter import get_splitter_for
from .mimetype_list import SUPPORTED_MIMETYPES


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


def _sources_to_documents(sources: list[UploadFile]) -> dict[str, list[Document]]:
	'''
	Converts a list of sources to a dictionary of documents with the user_id as the key.
	'''
	documents = {}

	for source in sources:
		user_id = source.headers.get('userId')
		if user_id is None:
			log_error(f'userId not found in headers for source: {source.filename}')
			continue

		# transform the source to have text data
		content = decode_source(source)
		if content is None or content == '':
			continue

		metadata = {
			'source': source.filename,
			'title': source.headers.get('title'),
			'type': source.headers.get('type'),
			'modified': source.headers.get('modified'),
			'provider': source.headers.get('provider'),
		}

		document = Document(page_content=content, metadata=metadata)

		if documents.get(user_id) is not None:
			documents[user_id].append(document)
		else:
			documents[user_id] = [document]

	return documents


def _bucket_by_type(documents: list[Document]) -> dict[str, list[Document]]:
	bucketed_documents = {}

	for doc in documents:
		doc_type = doc.metadata.get('type')

		if bucketed_documents.get(doc_type) is not None:
			bucketed_documents[doc_type].append(doc)
		else:
			bucketed_documents[doc_type] = [doc]

	return bucketed_documents


def _process_sources(vectordb: BaseVectorDB, sources: list[UploadFile]) -> bool:
	try:
		filtered_sources = _filter_sources(sources[0].headers['userId'], vectordb, sources)
	except DbException as e:
		log_error(e)
		return False

	if len(filtered_sources) == 0:
		# no new sources to embed
		return True

	ddocuments: dict[str, list[Document]] = _sources_to_documents(filtered_sources)

	if len(ddocuments.keys()) == 0:
		# document(s) were empty, not an error
		return True

	success = True

	for user_id, documents in ddocuments.items():
		split_documents: list[Document] = []

		type_bucketed_docs = _bucket_by_type(documents)

		for _type, _docs in type_bucketed_docs.items():
			text_splitter = get_splitter_for(_type)
			split_docs = text_splitter.split_documents(_docs)
			split_documents.extend(split_docs)

		# replace more than two newlines with two newlines (also blank spaces, more than 4)
		for doc in split_documents:
			doc.page_content = re.sub(r'((\r)?\n){3,}', '\n\n', doc.page_content)
			# NOTE: do not use this with all docs when programming files are added
			doc.page_content = re.sub(r'(\s){5,}', r'\g<1>', doc.page_content)

		# filter out empty documents
		split_documents = list(filter(lambda doc: doc.page_content != '', split_documents))
		if len(split_documents) == 0:
			continue

		try:
			user_client = vectordb.get_user_client(user_id)
		except DbException as e:
			log_error(e)
			return False

		doc_ids = user_client.add_documents(split_documents)

		# does not do per document error checking
		success &= len(split_documents) == len(doc_ids)

	return success


def embed_sources(
	vectordb: BaseVectorDB,
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
	return _process_sources(vectordb, sources_filtered)
