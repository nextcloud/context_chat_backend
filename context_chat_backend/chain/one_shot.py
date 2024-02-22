from enum import Enum
from logging import error as log_error

from langchain.llms.base import LLM

from ..vectordb import BaseVectorDB

_LLM_TEMPLATE = '''Answer based only on this context and do not add any imaginative details:
{context}

{question}
'''


class ScopeType(Enum):
	PROVIDER = 'provider'
	SOURCE = 'source'


def process_query(
	user_id: str,
	vectordb: BaseVectorDB,
	llm: LLM,
	query: str,
	use_context: bool = True,
	ctx_limit: int = 5,
	ctx_filter: dict | None = None,
	template: str | None = None,
	end_separator: str = '',
) -> tuple[str, list[str]]:
	if not use_context:
		return llm.predict(query), set()

	user_client = vectordb.get_user_client(user_id)
	if user_client is None:
		return llm.predict(query), set()

	if ctx_filter is not None:
		context_docs = user_client.similarity_search(query, k=ctx_limit, filter=ctx_filter)
	else:
		context_docs = user_client.similarity_search(query, k=ctx_limit)

	context_text = '\n\n'.join(f'{d.metadata.get("title")}\n{d.page_content}' for d in context_docs)

	output = llm.predict((template or _LLM_TEMPLATE).format(context=context_text, question=query)) \
		.strip().rstrip(end_separator).strip()
	unique_sources: list[str] = list({source for d in context_docs if (source := d.metadata.get('source'))})

	return (output, unique_sources)


def process_scoped_query(
	user_id: str,
	vectordb: BaseVectorDB,
	llm: LLM,
	query: str,
	scope_type: ScopeType,
	scope_list: list[str],
	ctx_limit: int = 5,
	template: str | None = None,
	end_separator: str = '',
) -> tuple[str, list[str]]:
	ctx_filter = vectordb.get_metadata_filter([{
		'metadata_key': scope_type.value,
		'values': scope_list,
	}])

	if ctx_filter is None:
		log_error(f'Error: could not get filter for (\nscope type: {scope_type}\n\
scope list: {scope_list}\n\nproceeding with an unscoped query')

	return process_query(
		user_id=user_id,
		vectordb=vectordb,
		llm=llm,
		query=query,
		use_context=True,
		ctx_limit=ctx_limit,
		ctx_filter=ctx_filter,
		template=template,
		end_separator=end_separator,
	)
