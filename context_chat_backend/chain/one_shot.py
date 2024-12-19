#
# SPDX-FileCopyrightText: 2023 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
from langchain.llms.base import LLM

from ..dyn_loader import VectorDBLoader
from ..types import TConfig
from .context import get_context_chunks, get_context_docs
from .query_proc import get_pruned_query
from .types import ContextException, LLMOutput, ScopeType

_LLM_TEMPLATE = '''
You're an AI assistant named Nextcloud Assistant, good at finding relevant context from documents to answer questions provided by the user.
Use the following documents as context to answer the question at the end. REMEMBER to exercise source criticism as the documents are returned by a search provider that can return unrelated documents.
If you don't know the answer or are unsure, just say that you don't know, don't try to make up an answer. Don't mention the context in your answer but rather just answer the question directly. Detect the language of the question and make sure to use the same language that was used in the question to answer the question.
Don't mention which language was used, but just answer the question directly in the same langauge.

QUESTION:
-----------------

{question}

-----------------
END OF QUESTION

CONTEXT:
-----------------

{context}

-----------------
END OF CONTEXT

Let's think this step-by-step. Answer the question:
''' # noqa: E501


def process_query(
	user_id: str,
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
		userid=user_id,
	).strip()

	return LLMOutput(output=output, sources=[])


def process_context_query(
	user_id: str,
	vectordb_loader: VectorDBLoader,
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
	db = vectordb_loader.load()
	context_docs = get_context_docs(user_id, query, db, ctx_limit, scope_type, scope_list)
	if len(context_docs) == 0:
		raise ContextException('No documents retrieved, please index a few documents first')

	context_chunks = get_context_chunks(context_docs)
	print('len(context_chunks)', len(context_chunks), flush=True)

	output = llm.invoke(
		get_pruned_query(llm, app_config, query, template or _LLM_TEMPLATE, context_chunks),
		stop=[end_separator],
		userid=user_id,
	).strip()
	unique_sources: list[str] = list({source for d in context_docs if (source := d.metadata.get('source'))})

	return LLMOutput(output=output, sources=unique_sources)
