import multiprocessing as mp

from langchain.llms.base import LLM
from typing_extensions import TypedDict

from ..config_parser import TConfig
from ..vectordb import BaseVectorDB
from .context import ContextException, ScopeType, get_context_chunks, get_context_docs
from .query_proc import get_pruned_query

_LLM_TEMPLATE = '''Answer based only on this context and do not add any imaginative details. Make sure to use the same language as the question in your answer.
{context}

{question}
''' # noqa: E501


class LLMOutput(TypedDict):
	output: str
	sources: list[str]


def process_query(
	result_queue: mp.Queue,
	llm: LLM,
	app_config: TConfig,
	query: str,
	no_ctx_template: str | None = None,
	end_separator: str = '',
):
	"""
	Raises
	------
	ValueError
		If the context length is too small to fit the query
	"""
	stop = [end_separator] if end_separator else None
	output = llm.invoke(
		(query, get_pruned_query(llm, app_config, query, no_ctx_template, []))[no_ctx_template is not None],  # pyright: ignore[reportArgumentType]
		stop=stop,
	).strip()

	result_queue.put(LLMOutput(output=output, sources=[]))


def process_context_query(
	result_queue: mp.Queue,
	user_id: str,
	vectordb: BaseVectorDB,
	llm: LLM,
	app_config: TConfig,
	query: str,
	ctx_limit: int = 20,
	scope_type: ScopeType | None = None,
	scope_list: list[str] | None = None,
	template: str | None = None,
	end_separator: str = '',
):
	"""
	Raises
	------
	ValueError
		If the context length is too small to fit the query
	"""
	context_docs = get_context_docs(user_id, query, vectordb, ctx_limit, scope_type, scope_list)
	if len(context_docs) == 0:
		raise ContextException('No documents retrieved, please index a few documents first to use context-aware mode')

	context_chunks = get_context_chunks(context_docs)
	print('len(context_chunks)', len(context_chunks), flush=True)

	output = llm.invoke(
		get_pruned_query(llm, app_config, query, template or _LLM_TEMPLATE, context_chunks),
		stop=[end_separator],
	).strip()
	unique_sources: list[str] = list({source for d in context_docs if (source := d.metadata.get('source'))})

	result_queue.put(LLMOutput(output=output, sources=unique_sources))
