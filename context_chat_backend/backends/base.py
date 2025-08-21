# ruff: noqa: I001
from __future__ import annotations
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any


class RagBackend:
    """Stable interface between CCBE endpoints and any RAG backend."""

    # --- Collections / tenancy
    def ensure_collections(self, user_ids: Sequence[str]) -> dict[str, str]:
        """Ensure per-user collections; return {user_id: collection_id}."""
        raise NotImplementedError

    # --- Documents
    def list_documents(self, offset: int = 0, limit: int = 100) -> list[dict]:
        raise NotImplementedError

    def find_document_by_title(self, title: str) -> dict | None:
        """Return provider doc object (must include 'id', 'metadata', 'collection_ids') or None."""
        raise NotImplementedError

    def upsert_document(
        self,
        file_path: str,
        metadata: Mapping[str, Any],
        collection_ids: Sequence[str],
    ) -> str:
        """Create or replace; return document_id."""
        raise NotImplementedError

    def delete_document(self, document_id: str) -> None:
        raise NotImplementedError

    # --- Access control
    def update_access(
        self,
        op: UpdateAccessOp,
        user_ids: Sequence[str],
        document_id: str,
    ) -> None:
        """Allow or deny ``user_ids`` access to ``document_id``."""
        raise NotImplementedError

    def decl_update_access(
        self,
        user_ids: Sequence[str],
        document_id: str,
    ) -> None:
        """Set exact ``user_ids`` allowed to access ``document_id``."""
        raise NotImplementedError

    # --- Retrieval
    def search(
        self,
        user_id: str,
        query: str,
        ctx_limit: int,
        scope_type: str | None = None,
        scope_list: Sequence[str] | None = None,
    ) -> list[dict]:
        """Return ranked chunks with at least: text/page_content, metadata dict."""
        raise NotImplementedError

    def config(self) -> dict[str, Any]:
        """Return a serialisable snapshot of backend configuration."""
        return {}


if TYPE_CHECKING:
    from context_chat_backend.vectordb.types import UpdateAccessOp
