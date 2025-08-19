"""R2R backend using direct HTTP requests.

This backend communicates with an external R2R service over the network
instead of relying on the optional :mod:`r2r` Python package.  The service
base URL is taken from the ``R2R_BASE_URL`` environment variable and defaults
to ``http://127.0.0.1:7272``.  If the target instance requires authentication,
set ``R2R_API_KEY`` to an API key (sent as ``X-API-Key``) and/or
``R2R_API_TOKEN`` to a bearer token (``Authorization: Bearer …``).

Only a minimal subset of the R2R API is implemented - enough for the Context
Chat backend to manage collections, documents and to perform search queries.
"""

from __future__ import annotations

import json
import logging
import os
import shlex
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from .base import RagBackend

logger = logging.getLogger(__name__)

class R2rBackend(RagBackend):
    """Implementation of :class:`RagBackend` that talks to an R2R service."""

    def __init__(self) -> None:
        base = os.getenv("R2R_BASE_URL", "http://127.0.0.1:7272").rstrip("/")
        token = os.getenv("R2R_API_TOKEN")
        api_key = os.getenv("R2R_API_KEY")
        headers: dict[str, str] = {}
        if api_key:
            headers["X-API-Key"] = api_key
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.Client(base_url=base, timeout=30.0, headers=headers)

        # Echo the curl command for lifecycle checks and easier debugging.
        curl_parts = ["curl", "-i"]
        for key, value in headers.items():
            curl_parts.extend(["-H", f"{key}: {value}"])
        curl_parts.append(f"{base}/v3/system/status")
        cmd = " ".join(shlex.quote(part) for part in curl_parts)
        logger.info("R2R healthcheck command: %s", cmd)
        # Logging is configured after backend initialization. Use ``print``
        # so the command is still visible in container logs during startup.
        print(f"R2R healthcheck command: {cmd}", flush=True)

        # Fail fast - used by the /init job as well. ``/v3/system/status`` is a
        # public endpoint that does not require special permissions and is the
        # recommended way to verify service availability.
        resp = self._client.get("/v3/system/status")
        resp.raise_for_status()

    # ------------------------------------------------------------------
    # Utility helpers
    def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        url_path = f"/v3/{path.lstrip('/')}"
        curl_parts = ["curl", "-i", "-X", method.upper()]
        for key, value in self._client.headers.items():
            curl_parts.extend(["-H", f"{key}: {value}"])
        curl_parts.append(f"{self._client.base_url}{url_path}")
        cmd = " ".join(shlex.quote(part) for part in curl_parts)
        logger.info("R2R request: %s", cmd)
        print(f"R2R request: {cmd}", flush=True)

        resp = self._client.request(method, url_path, **kwargs)
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    # ------------------------------------------------------------------
    # Collections
    def ensure_collections(self, user_ids: Sequence[str]) -> dict[str, str]:
        offset, limit = 0, 100
        existing: dict[str, str] = {}
        while True:
            coll = self._request(
                "GET", "collections", params={"offset": offset, "limit": limit}
            )
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
                created = self._request(
                    "POST",
                    "collections",
                    json={
                        "name": uid,
                        "description": f"Auto-generated collection for user {uid}",
                    },
                )
                mapping[uid] = created.get("results", {}).get("id")
        return mapping

    # ------------------------------------------------------------------
    # Documents
    def list_documents(self, offset: int = 0, limit: int = 100) -> list[dict]:
        docs = self._request(
            "GET", "documents", params={"offset": offset, "limit": limit}
        )
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
            same = em.get("modified") == metadata.get("modified") and em.get(
                "content-length"
            ) == metadata.get("content-length")
            if same:
                current = set(existing.get("collection_ids", []))
                target = set(collection_ids)
                add = target - current
                rem = current - target
                for cid in add:
                    self._request("POST", f"collections/{cid}/documents/{existing['id']}")
                for cid in rem:
                    self._request(
                        "DELETE", f"collections/{cid}/documents/{existing['id']}"
                    )
                return existing["id"]

            self.delete_document(existing["id"])

        with open(file_path, "rb") as fh:
            files = {
                "file": (
                    metadata.get("filename") or os.path.basename(file_path),
                    fh,
                    "application/octet-stream",
                )
            }
            data = {
                "metadata": json.dumps(metadata),
                "collection_ids": json.dumps(list(collection_ids)),
                "ingestion_mode": "fast",
            }
            created = self._request("POST", "documents", data=data, files=files)
        return created.get("results", {}).get("document_id", "")

    def delete_document(self, document_id: str) -> None:
        self._request("DELETE", f"documents/{document_id}")

    # ------------------------------------------------------------------
    # Retrieval (minimal shape)
    def search(
        self,
        user_id: str,
        query: str,
        ctx_limit: int,
        scope_type: str | None = None,
        scope_list: Sequence[str] | None = None,
    ) -> list[dict]:
        payload = {
            "query": query,
            "user_id": user_id,
            "top_k": ctx_limit,
        }
        if scope_type and scope_list:
            payload["scope"] = {"type": scope_type, "ids": list(scope_list)}
        resp = self._request("POST", "retrieval/search", json=payload)
        out = []
        for hit in resp.get("results", []):
            out.append(
                {
                    "page_content": hit.get("text") or hit.get("content", ""),
                    "metadata": hit.get("metadata", {}),
                }
            )
        return out


# Backwards compatibility for earlier imports
R2RBackend = R2rBackend
