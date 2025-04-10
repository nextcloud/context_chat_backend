#
# SPDX-FileCopyrightText: 2024 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
import logging

from langchain.schema import Document

from ..vectordb.base import BaseVectorDB
from .types import ContextException, ScopeType

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
