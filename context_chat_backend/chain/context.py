#
# SPDX-FileCopyrightText: 2024 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
import logging

from langchain.schema import Document

from ..dyn_loader import VectorDBLoader
from ..vectordb.base import BaseVectorDB
from .types import ContextException, ScopeType, SearchResult

logger = logging.getLogger('ccb.chain')

def get_context_docs(
	user_id: str,
	query: str,
	vectordb: BaseVectorDB,
	ctx_limit: int,
	scope_type: ScopeType | None = None,
	scope_list: list[str] | None = None,
) -> list[Document]:
	# unscoped search
	if not scope_type:
		logger.debug('Searching for context docs without scope')
		return vectordb.doc_search(user_id, query, ctx_limit)

	if not scope_list:
		raise ContextException('Error: scope list must be provided and not empty if scope type is provided')

	logger.debug('Searching for context docs with scope')
	return vectordb.doc_search(user_id, query, ctx_limit, scope_type, scope_list)


def get_context_chunks(context_docs: list[Document]) -> list[str]:
	context_chunks = []
	for doc in context_docs:
		if title := doc.metadata.get('title'):
			context_chunks.append(title)
		context_chunks.append(doc.page_content)

	return context_chunks


def do_doc_search(
	user_id: str,
	query: str,
	vectordb_loader: VectorDBLoader,
	ctx_limit: int = 20,
	scope_type: ScopeType | None = None,
	scope_list: list[str] | None = None,
) -> list[SearchResult]:
	"""
	Raises
	------
	ContextException
		If the scope type is provided but the scope list is empty or not provided
	"""
	db = vectordb_loader.load()
	augmented_limit = ctx_limit * 2 # to account for duplicate sources
	docs = get_context_docs(user_id, query, db, augmented_limit, scope_type, scope_list)
	if len(docs) == 0:
		logger.warning('No documents retrieved, please index a few documents first')
		return []

	sources_cache = {}
	results: list[SearchResult] = []
	for doc in docs:
		source_id = doc.metadata.get('source')
		if not source_id:
			logger.warning('Document without source id encountered in doc search, skipping', extra={
				'doc': doc,
			})
			continue
		if source_id in sources_cache:
			continue
		if len(results) >= ctx_limit:
			break

		sources_cache[source_id] = None
		results.append(SearchResult(
			source_id=source_id,
			title=doc.metadata.get('title', ''),
		))

	logger.debug('do_doc_search', extra={
		'len(docs)': len(docs),
		'len(results)': len(results),
		'scope_type': scope_type,
		'scope_list': scope_list,
	})
	return results
