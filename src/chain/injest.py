from typing import List, Iterator
from werkzeug.datastructures.file_storage import FileStorage
from langchain.vectorstores import VectorStore
from langchain.text_splitter import (
	TextSplitter,
	RecursiveCharacterTextSplitter,
	MarkdownTextSplitter,
)

from ..utils import to_int


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
		# TODO: some storage vs performance cost tests for chunk size
		"chunk_size": 2000,
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


# TODO: vectordb is a langchain user client, init it before calling this function
def embed_files(vectordb: VectorStore, filesIter: Iterator[FileStorage]) -> List[str]:
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

	for text, meta in zip(contents, metas):
		text_splitter = _get_splitter_for(meta.get("type"))
		docs = text_splitter.create_documents([text], [meta])
		if len(docs) == 0:
			continue
		documents.append(docs[0])

	return vectordb.add_documents(documents)


def embed_texts(vectordb: VectorStore, texts: List[dict]) -> List[str]:
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

	for text, meta in zip(contents, metas):
		text_splitter = _get_splitter_for(meta.get("type"))
		docs = text_splitter.create_documents([text], [meta])
		if len(docs) == 0:
			continue
		documents.append(docs[0])

	return vectordb.add_documents(documents)
