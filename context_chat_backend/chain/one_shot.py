from enum import Enum
from logging import error as log_error

from langchain.llms.base import LLM

from ..config_parser import TConfig
from ..utils import not_none
from ..vectordb import BaseVectorDB

_LLM_TEMPLATE = '''Answer based only on this context and do not add any imaginative details:
{context}

{question}
'''


class ScopeType(Enum):
	PROVIDER = 'provider'
	SOURCE = 'source'


def _get_pruned_query(llm: LLM, config: TConfig, query: str, template: str, text_chunks: list[str]) -> str:
	'''
	Truncates the input to fit the model's maximum context length
	and returns the model's prediction

	Raises
	------
	ValueError
		If the context length is too small to fit the query
	'''
	llm_config = config['llm'][1]
	n_ctx = llm_config.get('n_ctx') \
		or llm_config.get('config', {}).get('context_length') \
		or llm_config.get('pipeline_kwargs', {}).get('config', {}).get('max_length') \
		or 4096

	query_tokens = llm.get_num_tokens(query)
	template_tokens = llm.get_num_tokens(template.format(context='', question=''))

	remaining_tokens = n_ctx - template_tokens - query_tokens

	# If the query is too long to fit in the context, truncate it (keeping the template)
	if remaining_tokens <= 0:
		new_remaining_tokens = n_ctx - template_tokens
		while query and llm.get_num_tokens(query) > new_remaining_tokens:
			query = ' '.join(query.split()[:-10])

		if not query:
			raise ValueError('Context length is too small even to fit the template')

		return template.format(context='', question=query)

	accepted_chunks = []

	while text_chunks and remaining_tokens > 0:
		context = text_chunks.pop(0)
		context_tokens = llm.get_num_tokens(context)

		if context_tokens <= remaining_tokens:
			accepted_chunks.append(context)
			remaining_tokens -= context_tokens

	return template.format(context='\n\n'.join(accepted_chunks), question=query)


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
			(query, _get_pruned_query(llm, llm_config, query, no_ctx_template, []))[no_ctx_template is not None],
			stop=stop,
		), []

	user_client = vectordb.get_user_client(user_id)
	if user_client is None:
		stop = [end_separator] if end_separator else None
		return llm.invoke(
			(query, _get_pruned_query(llm, llm_config, query, no_ctx_template, []))[no_ctx_template is not None],
			stop=stop,
		), []

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

	context_chunks = []
	for doc in context_docs:
		if title := doc.metadata.get('title'):
			context_chunks.append(title)
		context_chunks.append(doc.page_content)

	output = llm.invoke(
		_get_pruned_query(llm, llm_config, query, template or _LLM_TEMPLATE, context_chunks),
		stop=[end_separator],
	).strip()
	unique_sources: list[str] = list({source for d in context_docs if (source := d.metadata.get('source'))})

	return (output, unique_sources)
