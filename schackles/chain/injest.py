from typing import List, Iterator, Optional
from werkzeug.datastructures.file_storage import FileStorage
from langchain.text_splitter import (
	TextSplitter,
	RecursiveCharacterTextSplitter,
	MarkdownTextSplitter,
)

from ..utils import to_int
from ..vectordb import BaseVectorDB


_ALLOWED_MIME_TYPES = [
	'text/plain',
	'text/markdown',
	'application/json',
]


def _allowed_file(file: FileStorage) -> bool:
	return file.headers \
		.get('type', type=str, default='') \
		.split('mimetype: ') \
		.pop() in _ALLOWED_MIME_TYPES


def _get_splitter_for(mimetype: str = "text/plain") -> TextSplitter:
	kwargs = {
		"chunk_size": 3000,
		"chunk_overlap": 200,
		"add_start_index": True,
		"strip_whitespace": True,
		"is_separator_regex": True,
	}

	if mimetype == "text/plain" or mimetype == "":
		return RecursiveCharacterTextSplitter(separators=["\n\n", "\n", ".", " ", ""], **kwargs)

	if mimetype == "text/markdown":
		return MarkdownTextSplitter(**kwargs)

	if mimetype == "application/json":
		return RecursiveCharacterTextSplitter(separators=["{", "}", "[", "]", ",", ""], **kwargs)


def _delete_old_sources(user_id: str, vectordb: BaseVectorDB, ids: List[str]) -> Optional[bool]:
	"""
	Deletes all documents with the given sources.
	"""
	client = vectordb.get_user_client(user_id)
	return client.delete(ids)


def _filter_sources(user_id: str, vectordb: BaseVectorDB, metas: List[dict]) -> List[str]:
	"""
	Returns a filtered list of documents that are not already in the vectordb
	or have been modified since they were last added.
	It also deletes the old documents to prevent duplicates.
	"""
	to_delete = {}

	dmetas = {}
	for meta in metas:
		dmetas[meta.get("source")] = meta

	existing_objects = vectordb.get_objects_from_sources(user_id, dmetas.keys())
	# case-sensitive check since some vector databases are have case-insensitive filters
	for source, existing_meta in existing_objects.items():
		# recently modified files are re-embedded
		if dmetas.get(source) is not None and \
			dmetas.get(source).get("modified") > existing_meta.get("modified"):
			to_delete[source] = existing_meta

	# delete old sources
	_delete_old_sources(user_id, vectordb, [meta.get("id") for meta in to_delete.values()])

	# sources not already in the vectordb + the ones that were deleted
	new_sources = set(dmetas.keys()) \
		.difference(set(existing_objects)) \
		.add(to_delete.keys())

	return list(new_sources)


def embed_files(
		user_id: str,
		vectordb: BaseVectorDB,
		filesIter: Iterator[FileStorage]
	) -> List[str]:
	print("embedding files...")

	files = list(filter(_allowed_file, filesIter))

	contents = []
	metas = []
	for file in files:
		contents.append(file.stream.read().decode())
		metas.append({
			"source": file.name,
			"type": file.headers.get("type", type=str),
			"modified": to_int(file.headers.get("modified", 0)),
		})

	if len(contents) == 0:
		return []

	documents = []
	sources_to_embed = _filter_sources(user_id, vectordb, metas)

	for text, meta in zip(contents, metas):
		if meta.get("source") not in sources_to_embed:
			continue

		text_splitter = _get_splitter_for(meta.get("type"))
		docs = text_splitter.create_documents([text], [meta])
		if len(docs) == 0:
			continue
		documents.append(docs[0])

	return vectordb.add_documents(documents)


def embed_texts(
		user_id: str,
		vectordb: BaseVectorDB,
		texts: List[dict]
	) -> List[str]:
	print("embedding texts...")

	contents = [text.get("contents") for text in texts]
	metas = [{
		"source": text.get("name"),
		"type": text.get("type"),
		"modified": to_int(text.get("modified", 0)),
	} for text in texts]

	if len(contents) == 0:
		return []

	documents = []
	sources_to_embed = _filter_sources(user_id, vectordb, metas)

	for text, meta in zip(contents, metas):
		if meta.get("source") not in sources_to_embed:
			continue

		text_splitter = _get_splitter_for(meta.get("type"))
		docs = text_splitter.create_documents([text], [meta])
		if len(docs) == 0:
			continue
		documents.append(docs[0])

	return vectordb.add_documents(documents)
