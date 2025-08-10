from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from typing import Any

from .base import RagBackend

try:
    from r2r import R2RClient
except Exception:  # pragma: no cover - dependency optional
    R2RClient = None  # type: ignore


class R2RBackend(RagBackend):
    def __init__(self) -> None:
        if R2RClient is None:
            raise RuntimeError("r2r package is not installed")
        base = os.getenv("R2R_BASE_URL", "http://127.0.0.1:7272")
        self.client = R2RClient(base)
        # fail fast on boot used by /init job as well
        self.client.system.settings()

    # ----------- Collections
    def ensure_collections(self, user_ids: Sequence[str]) -> dict[str, str]:
        offset, limit = 0, 100
        existing: dict[str, str] = {}
        while True:
            coll = self.client.collections.list(offset=offset, limit=limit)
            results = coll.get("results", [])
            if not results:
                break
            for c in results:
                existing[c["name"]] = c["id"]
            offset += limit

        mapping: dict[str, str] = {}
        for uid in {u.strip() for u in user_ids if u and u.strip()}:
            if uid in existing:
                mapping[uid] = existing[uid]
            else:
                created = self.client.collections.create(
                    name=uid,
                    description=f"Auto-generated collection for user {uid}",
                )
                mapping[uid] = created["results"]["id"]
        return mapping

    # ----------- Documents
    def list_documents(self, offset: int = 0, limit: int = 100) -> list[dict]:
        docs = self.client.documents.list(limit=limit, offset=offset)
        return docs.get("results", [])

    def find_document_by_title(self, title: str) -> dict | None:
        offset, limit = 0, 100
        while True:
            results = self.list_documents(offset=offset, limit=limit)
            if not results:
                return None
            for d in results:
                if d.get("metadata", {}).get("title") == title:
                    return d
            offset += limit

    def upsert_document(
        self,
        file_path: str,
        metadata: Mapping[str, Any],
        collection_ids: Sequence[str],
    ) -> str:
        if isinstance(collection_ids, str):
            raise ValueError("collection_ids must be a list of UUID strings")

        existing = self.find_document_by_title(metadata.get("title", ""))
        if existing:
            em = existing.get("metadata", {})
            same = em.get("modified") == metadata.get("modified") and em.get("content-length") == metadata.get(
                "content-length"
            )
            if same:
                current = set(existing.get("collection_ids", []))
                target = set(collection_ids)
                add = target - current
                rem = current - target
                for cid in add:
                    self.client.collections.add_document(cid, existing["id"])
                for cid in rem:
                    self.client.collections.remove_document(cid, existing["id"])
                return existing["id"]

            self.delete_document(existing["id"])

        created = self.client.documents.create(
            file_path=file_path,
            metadata=metadata,
            collection_ids=list(collection_ids),
            ingestion_mode="fast",
        )
        return created["results"]["document_id"]

    def delete_document(self, document_id: str) -> None:
        self.client.documents.delete(id=document_id)

    # ----------- Retrieval (minimal shape)
    def search(
        self,
        user_id: str,
        query: str,
        ctx_limit: int,
        scope_type: str | None = None,
        scope_list: Sequence[str] | None = None,
    ) -> list[dict]:
        resp = self.client.search.query(
            query=query,
            user_id=user_id,
            top_k=ctx_limit,
            scope_type=scope_type,
            scope_list=list(scope_list) if scope_list else None,
        )
        out = []
        for hit in resp.get("results", []):
            out.append(
                {
                    "page_content": hit.get("text") or hit.get("content", ""),
                    "metadata": hit.get("metadata", {}),
                }
            )
        return out
