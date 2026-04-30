#
# SPDX-FileCopyrightText: 2023 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
import logging

from langchain.llms.base import LLM

from ..dyn_loader import VectorDBLoader
from ..types import TConfig
from .context import get_context_docs
from .query_proc import get_pruned_query
from .types import ContextException, LLMOutput, ScopeType, SearchResult

_LLM_TEMPLATE = '''You're an AI assistant named Nextcloud Assistant, good at finding relevant context from documents to answer questions provided by the user.
Use the following documents as context to answer the question at the end. REMEMBER to excersice source critisicm as the documents are returned by a search provider that can return unrelated documents.

START OF CONTEXT:
{context}

END OF CONTEXT!

If you don't know the answer or are unsure, just say that you don't know, don't try to make up an answer.
Don't mention the context in your answer but rather just answer the question directly.
Detect the language of the question and make sure to use the same language that was used in the question to answer the question.
Don't mention which language was used, but just answer the question directly in the same langauge.

Question: {question}

Let's think this step-by-step.
''' # noqa: E501

logger = logging.getLogger('ccb.chain')

def process_context_query(
	user_id: str,
	vectordb_loader: VectorDBLoader,
	llm: LLM,
	app_config: TConfig,
	query: str,
	ctx_limit: int = 30,
	scope_type: ScopeType | None = None,
	scope_list: list[str] | None = None,
	template: str | None = None,
):
	"""
	Raises
	------
	ValueError
		If the context length is too small to fit the query
	"""
	db = vectordb_loader.load()
	context_docs = get_context_docs(user_id, query, db, ctx_limit, scope_type, scope_list)
	if len(context_docs) == 0:
		if scope_type is not None:
			raise ContextException('No documents retrieved, please choose a wider scope of documents to search from')
		raise ContextException('No documents retrieved, please index a few documents first')

	logger.debug('context retrieved', extra={
		'len(context_docs)': len(context_docs),
	})

	output = llm.invoke(
		get_pruned_query(llm, app_config, query, template or _LLM_TEMPLATE, context_docs),
		userid=user_id,
	).strip()
	unique_sources = [SearchResult(
		source_id=source,
		title=d.metadata.get('title', ''),
	) for d in context_docs if (source := d.metadata.get('source'))]

	return LLMOutput(output=output, sources=unique_sources)
