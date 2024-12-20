#
# SPDX-FileCopyrightText: 2024 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
from langchain.schema import Document

from ..vectordb.base import BaseVectorDB
from .types import ContextException, ScopeType


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
		return vectordb.doc_search(user_id, query, ctx_limit)

	if not scope_list:
		raise ContextException('Error: scope list must be provided and not empty if scope type is provided')

	return vectordb.doc_search(user_id, query, ctx_limit, scope_type, scope_list)


def get_context_chunks(context_docs: list[Document]) -> list[str]:
	context_chunks = []
	for doc in context_docs:
		chunk = '\n\nSTART OF DOCUMENT'
		if title := doc.metadata.get('title'):
			chunk += '\nDocument: ' + title
		chunk += "\n\n" + doc.page_content + "\n\nEND OF DOCUMENT"
		context_chunks.append(chunk)

	return context_chunks
