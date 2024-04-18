from langchain.llms.base import LLM

from ..config_parser import TConfig
from ..vectordb import BaseVectorDB
from .context import ScopeType, get_context_chunks, get_context_docs
from .query_proc import get_pruned_query

_LLM_TEMPLATE = '''Answer based only on this context and do not add any imaginative details:
{context}

{question}
'''


def process_query(
	user_id: str,
	vectordb: BaseVectorDB,
	llm: LLM,
	query: str,
	use_context: bool = True,
	ctx_limit: int = 10,
	scope_type: ScopeType | None = None,
	scope_list: list[str] | None = None,
	template: str | None = None,
	no_ctx_template: str | None = None,
	end_separator: str = '',
	llm_config: TConfig | None = None,
) -> tuple[str, list[str]]:
	"""
	Raises
	------
	ValueError
		If the context length is too small to fit the query
	"""
	if not use_context:
		stop = [end_separator] if end_separator else None
		return llm.invoke(
			(query, get_pruned_query(llm, llm_config, query, no_ctx_template, []))[no_ctx_template is not None],
			stop=stop,
		), []

	context_docs = get_context_docs(user_id, query, vectordb, ctx_limit, scope_type, scope_list)
	if context_docs is None:
		stop = [end_separator] if end_separator else None
		return llm.invoke(
			(query, get_pruned_query(llm, llm_config, query, no_ctx_template, []))[no_ctx_template is not None],
			stop=stop,
		), []

	context_chunks = get_context_chunks(context_docs)

	output = llm.invoke(
		get_pruned_query(llm, llm_config, query, template or _LLM_TEMPLATE, context_chunks),
		stop=[end_separator],
	).strip()
	unique_sources: list[str] = list({source for d in context_docs if (source := d.metadata.get('source'))})

	return (output, unique_sources)
