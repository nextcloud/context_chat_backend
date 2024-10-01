from enum import Enum

from langchain.schema import Document

from ..vectordb import BaseVectorDB


class ScopeType(Enum):
	PROVIDER = 'provider'
	SOURCE = 'source'


class ContextException(Exception):
	...


def get_context_docs(
	user_id: str,
	query: str,
	vectordb: BaseVectorDB,
	ctx_limit: int,
	scope_type: ScopeType | None = None,
	scope_list: list[str] | None = None,
) -> list[Document]:
	user_client = vectordb.get_user_client(user_id)

	# unscoped search
	if not scope_type:
		return user_client.similarity_search(query, k=ctx_limit)

	if not scope_list:
		raise ContextException('Error: scope list must be provided and not empty if scope type is provided')

	ctx_filter = vectordb.get_metadata_filter([{
		'metadata_key': scope_type.value,
		'values': scope_list,
	}])

	if ctx_filter is None:
		raise ContextException(f'Error: could not get filter for \nscope type: {scope_type}\nscope list: {scope_list}')

	return user_client.similarity_search(query, k=ctx_limit, filter=ctx_filter)


def get_context_chunks(context_docs: list[Document]) -> list[str]:
	context_chunks = []
	for doc in context_docs:
		if title := doc.metadata.get('title'):
			context_chunks.append(title)
		context_chunks.append(doc.page_content)

	return context_chunks
