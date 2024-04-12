from enum import Enum
from logging import error as log_error

from langchain.llms.base import LLM

from ..utils import not_none
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
	scope_type: ScopeType | None = None,
	scope_list: list[str] | None = None,
	template: str | None = None,
	no_ctx_template: str | None = None,
	end_separator: str = '',
) -> tuple[str, list[str]]:
	if not use_context:
		stop = [end_separator] if end_separator else None
		return llm.invoke((query, no_ctx_template.format(question=query))[no_ctx_template is not None], stop=stop), []

	user_client = vectordb.get_user_client(user_id)
	if user_client is None:
		stop = [end_separator] if end_separator else None
		return llm.invoke((query, no_ctx_template.format(question=query))[no_ctx_template is not None], stop=stop), []

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

	context_text = '\n\n'.join(f'{d.metadata.get("title")}\n{d.page_content}' for d in context_docs)

	output = llm.invoke(
		(template or _LLM_TEMPLATE).format(context=context_text, question=query),
		stop=[end_separator],
	).strip()
	unique_sources: list[str] = list({source for d in context_docs if (source := d.metadata.get('source'))})

	return (output, unique_sources)
