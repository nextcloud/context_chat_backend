#
# SPDX-FileCopyrightText: 2024 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
import logging
import os
from sys import maxsize as SYS_MAXSIZE

from langchain.llms.base import LLM
from transformers import GPT2Tokenizer

from ..types import TConfig

logger = logging.getLogger('ccb.chain')
__download_models_from_hf = os.environ.get('CC_DOWNLOAD_MODELS_FROM_HF', 'true').lower() in ('1', 'true', 'yes')


def get_num_tokens(text: str, tokenizer: GPT2Tokenizer) -> int:
	'''
	Returns the number of tokens in the text using the fast GPT2 tokenizer.
	'''
	return len(tokenizer.encode(text, max_length=SYS_MAXSIZE, truncation=True))


def get_pruned_query(llm: LLM, config: TConfig, query: str, template: str, text_chunks: list[str]) -> str:
	'''
	Truncates the input to fit the model's maximum context length
	and returns the model's prediction

	Raises
	------
	ValueError
		If the context length is too small to fit the query
	'''
	llm_config = config.llm[1]
	tokenizer = GPT2Tokenizer.from_pretrained('gpt2', local_files_only=(not __download_models_from_hf))

	# fav
	n_ctx = llm_config.get('n_ctx') \
		or llm_config.get('config', {}).get('context_length') \
		or llm_config.get('pipeline_kwargs', {}).get('config', {}).get('max_length') \
		or 8192

	# fav: tokens to generate
	n_gen = llm_config.get('max_tokens') \
		or llm_config.get('config', {}).get('max_new_tokens') \
		or max(
			llm_config.get('pipeline_kwargs', {}).get('config', {}).get('max_new_tokens', 0),
			llm_config.get('pipeline_kwargs', {}).get('config', {}).get('max_length', 0)
		) \
		or 4096

	query_tokens = get_num_tokens(query, tokenizer)
	template_tokens = get_num_tokens(template.format(context='', question=''), tokenizer)

	# remaining tokens after the template, query and 'to be' generated tokens
	remaining_tokens = n_ctx - template_tokens - query_tokens - n_gen

	# If the query is too long to fit in the context, truncate it (keeping the template)
	if remaining_tokens <= 0:
		new_remaining_tokens = n_ctx - template_tokens - n_gen
		while query and get_num_tokens(query, tokenizer) > new_remaining_tokens:
			query = ' '.join(query.split()[:-10])

		if not query:
			raise ValueError('Context length is too small even to fit the template')

		return template.format(context='', question=query)

	accepted_chunks = []

	while text_chunks and remaining_tokens > 0:
		context = text_chunks.pop(0)
		context_tokens = get_num_tokens(context, tokenizer)

		if context_tokens <= remaining_tokens:
			accepted_chunks.append(context)
			remaining_tokens -= context_tokens

	logger.debug('pruned query stats', extra={
		'total tokens': n_ctx - remaining_tokens,
		'remaining tokens': remaining_tokens,
		'accepted chunks': len(accepted_chunks),
		'total chunks': len(text_chunks),
	})

	return template.format(context='\n\n'.join(accepted_chunks), question=query)
