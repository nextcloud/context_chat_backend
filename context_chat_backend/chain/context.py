from enum import Enum
from logging import error as log_error

from langchain.schema import Document

from ..utils import not_none
from ..vectordb import BaseVectorDB, DbException


class ScopeType(Enum):
	PROVIDER = 'provider'
	SOURCE = 'source'


def get_context_docs(
	user_id: str,
	query: str,
	vectordb: BaseVectorDB,
	ctx_limit: int = 10,
	scope_type: ScopeType | None = None,
	scope_list: list[str] | None = None,
) -> list[Document] | None:
	try:
		user_client = vectordb.get_user_client(user_id)
	except DbException as e:
		log_error(e)
		return None

	context_docs = None
	if not_none(scope_type) and not_none(scope_list) and len(scope_list) > 0:
		ctx_filter = vectordb.get_metadata_filter([{
			'metadata_key': scope_type.value,
			'values': scope_list,
		}])

		if ctx_filter is not None:
			context_docs = user_client.similarity_search(query, k=ctx_limit, filter=ctx_filter)
		else:
			log_error(f'Error: could not get filter for \nscope type: {scope_type}\n\
scope list: {scope_list}\n\nproceeding with an unscoped query')

	if context_docs is None:
		context_docs = user_client.similarity_search(query, k=ctx_limit)

	return context_docs


def get_context_chunks(context_docs: list[Document]):
	context_chunks = []
	for doc in context_docs:
		if title := doc.metadata.get('title'):
			context_chunks.append(title)
		context_chunks.append(doc.page_content)

	return context_chunks
