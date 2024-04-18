from langchain.llms.base import LLM

from ..config_parser import TConfig


def get_pruned_query(llm: LLM, config: TConfig, query: str, template: str, text_chunks: list[str]) -> str:
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
