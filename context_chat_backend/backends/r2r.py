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

import hashlib
import json
import logging
import mimetypes
import os
import shlex
import time
from collections.abc import Mapping, Sequence
import threading
from typing import Any
from urllib.parse import urlencode

import httpx
import uuid

from ..vectordb.types import UpdateAccessOp
from ..log_context import request_id_var
from .base import RagBackend
from .errors import RetryableBackendBusy

logger = logging.getLogger("ccb.r2r")

class R2rBackend(RagBackend):
    """Implementation of :class:`RagBackend` that talks to an R2R service."""

    def __init__(self) -> None:
        base = os.getenv("R2R_BASE_URL", "http://127.0.0.1:7272").rstrip("/")
        token = os.getenv("R2R_API_TOKEN")
        api_key = os.getenv("R2R_API_KEY")
        self._base_url = base
        self._has_token = bool(token)
        self._has_api_key = bool(api_key)
        headers: dict[str, str] = {}
        if api_key:
            headers["X-API-Key"] = api_key
        if token:
            headers["Authorization"] = f"Bearer {token}"

        # Allow slow retrieval searches by using a generous default timeout.
        # ``R2R_HTTP_TIMEOUT`` (seconds) can override the default of 300.
        timeout_str = os.getenv("R2R_HTTP_TIMEOUT", "300")
        try:
            timeout = float(timeout_str)
        except ValueError:
            timeout = 300.0
        self._client = httpx.Client(base_url=base, timeout=timeout, headers=headers)

        # Local saturation metrics (caller-side): track in-flight upserts and EWMA RTT
        self._metrics_lock = threading.Lock()
        self._inflight_upserts = 0
        self._rtt_ewma_ms: float | None = None

        # Optional: proactively skip uploads for certain extensions before
        # contacting R2R. Keep this in sync with R2R's ga_r2r.toml when set.
        # Example: ".xls,.xlsx,.exe" (case-insensitive)
        exts_env = os.getenv("R2R_EXCLUDE_EXTS", "")
        self._excluded_exts: set[str] = {
            e if e.startswith(".") else f".{e}"
            for e in (s.strip().lower() for s in exts_env.split(","))
            if e
        }

        # Echo the curl command for lifecycle checks and easier debugging.
        curl_parts = ["curl", "-i"]
        for key, value in headers.items():
            curl_parts.extend(["-H", f"{key}: {value}"])
        curl_parts.append(f"{base}/v3/system/status")

        cmd = " ".join(shlex.quote(part) for part in curl_parts)
        logger.info("R2R healthcheck command: %s", cmd)


        # Fail fast - used by the /init job as well. ``/v3/system/status`` is a
        # public endpoint that does not require special permissions and is the
        # recommended way to verify service availability.
        resp = self._client.get("/v3/system/status")
        resp.raise_for_status()

    # ------------------------------------------------------------------
    # Optional capacity/backpressure probe
    def can_accept_ingestion(self) -> bool:
        """Return False when downstream queues look overloaded.

        This is best-effort and only activates when ``QUEUE_HEALTH_URL`` is set.
        It queries a RabbitMQ management API endpoint and applies simple
        thresholds. When not configured or on probe failure, returns True.
        """
        # First, check local synchronous indicators
        try:
            max_inflight = int(os.getenv("R2R_MAX_INFLIGHT_UPSERTS", "0") or 0)
        except Exception:
            max_inflight = 0
        try:
            max_rtt_ms = float(os.getenv("R2R_HEALTH_MAX_RTT_MS", "0") or 0)
        except Exception:
            max_rtt_ms = 0.0
        with self._metrics_lock:
            inflight = int(self._inflight_upserts)
            rtt_ewma = float(self._rtt_ewma_ms or 0.0)
        if max_inflight and inflight >= max_inflight:
            logger.info(
                "Backpressure: inflight upserts over threshold",
                extra={"inflight": inflight, "max_inflight": max_inflight},
            )
            return False
        if max_rtt_ms and rtt_ewma > max_rtt_ms:
            logger.info(
                "Backpressure: RTT EWMA over threshold",
                extra={"rtt_ms": round(rtt_ewma, 2), "max_rtt_ms": max_rtt_ms},
            )
            return False

        # Optional RabbitMQ mgmt-based gating
        base = os.getenv("QUEUE_HEALTH_URL", "").rstrip("/")
        max_total = int(os.getenv("QUEUE_MAX_MESSAGES", "0") or 0)
        max_per_consumer = int(os.getenv("QUEUE_MAX_PER_CONSUMER", "0") or 0)
        if not base or (not max_total and not max_per_consumer):
            return True
        user = os.getenv("QUEUE_HEALTH_USER")
        pwd = os.getenv("QUEUE_HEALTH_PASSWORD")
        try:
            url = f"{base}/api/queues"
            auth = None
            headers = {"Accept": "application/json"}
            if user and pwd:
                auth = (user, pwd)
            with httpx.Client(timeout=5.0) as c:
                resp = c.get(url, headers=headers, auth=auth)
                resp.raise_for_status()
                queues = resp.json() or []
        except Exception:
            # Do not block ingestion if probe fails
            return True

        try:
            total_ready = 0
            worst_ratio = 0.0
            for q in queues:
                ready = int(q.get("messages_ready") or 0)
                consumers = int(q.get("consumers") or 0)
                total_ready += ready
                if consumers > 0:
                    worst_ratio = max(worst_ratio, ready / max(1, consumers))
            if max_total and total_ready > max_total:
                logger.info(
                    "Backpressure: total_ready exceeds max_total",
                    extra={"total_ready": total_ready, "max_total": max_total},
                )
                return False
            if max_per_consumer and worst_ratio > float(max_per_consumer):
                logger.info(
                    "Backpressure: messages_ready per consumer over threshold",
                    extra={"worst_ratio": worst_ratio, "max_per_consumer": max_per_consumer},
                )
                return False
        except Exception:
            # Be permissive on any parsing errors
            return True

        return True

    # ------------------------------------------------------------------
    # Utility helpers
    def _request(
        self,
        method: str,
        path: str,
        *,
        action: str | None = None,
        desc: str | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        url_path = f"/v3/{path.lstrip('/')}"
        curl_parts = ["curl", "-i", "-X", method.upper()]
        # Merge client headers with any call-specific overrides.  Explicitly add
        # ``Content-Type: application/json`` for JSON or dict payloads so that
        # the generated curl command mirrors the actual request.
        headers = dict(self._client.headers)
        headers.update(kwargs.get("headers") or {})
        # Propagate request correlation id if present
        try:
            rid = request_id_var.get()
        except Exception:
            rid = None
        if rid:
            headers.setdefault("X-Request-ID", rid)
        if (
            ("json" in kwargs and kwargs["json"] is not None)
            or (
                "data" in kwargs
                and isinstance(kwargs["data"], dict | list)
            )
        ):
            headers.setdefault("Content-Type", "application/json")
        kwargs["headers"] = headers
        for key, value in headers.items():
            lower = key.lower()
            masked = value
            if lower == "authorization":
                scheme, _, _ = value.partition(" ")
                masked = f"{scheme} ***" if scheme else "***"
            elif lower == "x-api-key":
                masked = "***"
            curl_parts.extend(["-H", f"{key}: {masked}"])

        payload: str | None = None
        if "json" in kwargs and kwargs["json"] is not None:
            payload = json.dumps(kwargs["json"], sort_keys=True)
        elif "data" in kwargs and kwargs["data"] is not None:
            data = kwargs["data"]
            payload = (
                json.dumps(data, sort_keys=True)
                if isinstance(data, dict | list)
                else str(data)
            )
        if payload is not None:
            curl_parts.extend(["-d", payload])
            logger.debug("R2R request payload: %s", payload)

        files_arg = kwargs.get("files")
        if files_arg:
            items = files_arg.items() if isinstance(files_arg, dict) else files_arg
            for key, value in items:
                if isinstance(value, tuple | list):
                    filename = value[0] if len(value) > 0 else None
                    content_type = value[2] if len(value) > 2 else None
                    if filename is None:
                        part_val = value[1] if len(value) > 1 else ""
                        part = f"{key}={part_val}"
                    else:
                        ct = f";type={content_type}" if content_type else ""
                        part = f"{key}=@{filename}{ct}"
                else:
                    part = f"{key}={value}"
                curl_parts.extend(["-F", part])

        params = kwargs.get("params")
        query = f"?{urlencode(params, doseq=True)}" if params else ""
        curl_parts.append(f"{self._client.base_url}{url_path}{query}")

        cmd = " ".join(shlex.quote(part) for part in curl_parts)
        if desc:
            logger.info(desc)
        if action:
            logger.debug("R2R request [%s]: %s", action, cmd)
        else:
            logger.debug("R2R request: %s", cmd)
        start = time.perf_counter()
        resp = self._client.request(method, url_path, **kwargs)
        duration_ms = (time.perf_counter() - start) * 1000.0
        # Maintain a simple EWMA of request latencies as a saturation hint
        try:
            alpha = 0.2
            with self._metrics_lock:
                if self._rtt_ewma_ms is None:
                    self._rtt_ewma_ms = duration_ms
                else:
                    self._rtt_ewma_ms = alpha * duration_ms + (1 - alpha) * self._rtt_ewma_ms
        except Exception:
            pass
        logger.info(
            "R2R request completed",
            extra={
                "method": method.upper(),
                "path": url_path,
                "status": resp.status_code,
                "duration_ms": round(duration_ms, 2),
                "action": action or "",
            },
        )
        logger.debug("R2R response body: %s", resp.text)
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    # ------------------------------------------------------------------
    # Maintenance
    def _ensure_cache_setup(self) -> None:
        if not hasattr(self, "_cache_lock"):
            import threading as _th
            self._cache_lock = _th.Lock()
        if not hasattr(self, "_cache_path"):
            self._cache_path = os.getenv(
                "R2R_UPSERT_CACHE_PATH", "/app/persistent_storage/r2r_upsert_cache.json"
            )
        if not hasattr(self, "_upsert_cache"):
            self._upsert_cache = {}
            try:
                with open(self._cache_path, "r", encoding="utf-8") as fh:
                    self._upsert_cache = json.load(fh) or {}
            except FileNotFoundError:
                self._upsert_cache = {}
            except Exception:
                self._upsert_cache = {}
        # Skip windows (read lazily to support older images)
        if not hasattr(self, "_skip_all_within_secs"):
            try:
                self._skip_all_within_secs = int(os.getenv("R2R_SKIP_UPSERT_ALL_WITHIN_SECS", "0") or 0)
            except Exception:
                self._skip_all_within_secs = 0
        if not hasattr(self, "_skip_meta_within_secs"):
            try:
                self._skip_meta_within_secs = int(os.getenv("R2R_SKIP_UPSERT_META_WITHIN_SECS", "0") or 0)
            except Exception:
                self._skip_meta_within_secs = 0
    def seed_upsert_cache(
        self,
        *,
        per_page: int = 200,
        fetch_missing_details: bool = True,
        now_ts: float | None = None,
    ) -> dict[str, int]:
        """Seed the on-disk upsert cache from existing R2R documents.

        Iterates all documents available to the API, reads their
        ``metadata.sha256`` (optionally fetching details when the list lacks
        it), and stores entries keyed by sha256 with the current timestamp and
        doc_id. Existing entries are preserved and refreshed.

        Returns a stats dict with counts of processed/seeded/skipped.
        """
        self._ensure_cache_setup()
        stats = {"processed": 0, "seeded": 0, "refreshed": 0, "skipped_no_hash": 0}
        ts = now_ts or time.time()

        offset = 0
        while True:
            docs = self._request(
                "GET",
                "documents",
                action="seed_upsert_cache:list",
                params={"offset": offset, "limit": per_page},
            ).get("results", [])
            if not docs:
                break
            for d in docs:
                stats["processed"] += 1
                doc_id = d.get("id")
                meta = d.get("metadata") or {}
                sha = meta.get("sha256")
                if not sha and fetch_missing_details and doc_id:
                    try:
                        detail = self.get_document(str(doc_id))
                        meta = detail.get("metadata") or meta
                        sha = meta.get("sha256")
                    except Exception:
                        sha = None
                if not sha:
                    stats["skipped_no_hash"] += 1
                    continue

                entry = {
                    "ts": ts,
                    "doc_id": str(doc_id) if doc_id else "",
                    "filename": meta.get("filename", ""),
                }
                try:
                    with self._cache_lock:
                        existed = sha in self._upsert_cache
                        self._upsert_cache[sha] = entry
                        os.makedirs(os.path.dirname(self._cache_path), exist_ok=True)
                        with open(self._cache_path, "w", encoding="utf-8") as fh:
                            json.dump(self._upsert_cache, fh)
                        stats["refreshed" if existed else "seeded"] += 1
                except Exception:
                    # Best-effort; continue
                    pass
            offset += per_page

        logger.info(
            "Seeded upsert cache",
            extra={
                "processed": stats["processed"],
                "seeded": stats["seeded"],
                "refreshed": stats["refreshed"],
                "skipped_no_hash": stats["skipped_no_hash"],
                "cache_path": self._cache_path,
            },
        )
        return stats

    def seed_upsert_cache_from_export(
        self,
        *,
        export_path: str | None = None,
        now_ts: float | None = None,
        columns: list[str] | None = None,
        include_header: bool = True,
        max_rows: int | None = None,
        flush_every: int = 10000,
    ) -> dict[str, int]:
        """Seed the upsert cache using R2R CSV export for documents via POST.

        Default payload mirrors the docs example and requests specific columns
        so parsing is fast and reliable. If your deployment needs different
        columns, pass them via ``columns``.

        Args:
          export_path: Optional relative path under /v3 (default "documents/export").
          now_ts: Optional timestamp to stamp cache entries.
          columns: Optional column list (default: ["id","metadata.sha256","metadata.filename","metadata.source","title"]).
          include_header: Whether the CSV should include a header row.
        """
        import csv
        self._ensure_cache_setup()
        ts = now_ts or time.time()
        stats = {"processed": 0, "seeded": 0, "refreshed": 0, "skipped_no_hash": 0}

        rel = (export_path or "documents/export").lstrip("/")
        api_path = f"/v3/{rel}"
        # Many deployments do not allow dot-access columns. Default to
        # requesting the raw 'metadata' JSON and parse fields locally.
        cols = columns or ["id", "title", "metadata"]

        headers = {"Accept": "text/csv", "Content-Type": "application/json"}
        payload = {"columns": cols, "include_header": bool(include_header)}

        # Helper to perform one export
        def _stream_export(col_list: list[str]):
            body = {"columns": col_list, "include_header": bool(include_header)}
            return self._client.stream("POST", api_path, headers=headers, json=body)

        # First attempt with requested/default columns; on column errors, retry with safe fallback
        try:
            stream = _stream_export(cols)
        except httpx.HTTPStatusError:
            # Will be handled below by open+raise
            stream = _stream_export(["id", "title", "metadata"])

        with stream as resp:
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                # Retry once with safe fallback when API rejects column names
                if exc.response is not None and exc.response.status_code in {400, 422, 500}:
                    try:
                        with _stream_export(["id", "title", "metadata"]) as resp2:
                            resp2.raise_for_status()
                            resp = resp2  # type: ignore[assignment]
                    except Exception:
                        raise
                else:
                    raise

            def line_iter():
                buf = ""
                for chunk in resp.iter_text():
                    if not chunk:
                        continue
                    buf += chunk
                    while True:
                        pos = buf.find("\n")
                        if pos == -1:
                            break
                        line = buf[: pos + 1]
                        buf = buf[pos + 1 :]
                        yield line
                if buf:
                    yield buf

            reader = csv.DictReader(line_iter())
            for row in reader:
                stats["processed"] += 1
                if flush_every > 0 and (stats["processed"] % flush_every) == 0:
                    logger.info(
                        "Seeding export progress",
                        extra={"processed": stats["processed"], "seeded": stats["seeded"], "refreshed": stats["refreshed"]},
                    )
                doc_id = row.get("id") or row.get("document_id") or ""
                sha = row.get("metadata.sha256") or row.get("sha256")
                filename = row.get("metadata.filename") or row.get("filename") or row.get("metadata.source")
                if (not sha) or (not filename):
                    meta_json = row.get("metadata")
                    if meta_json:
                        try:
                            meta_obj = json.loads(meta_json)
                            sha = sha or meta_obj.get("sha256")
                            filename = filename or meta_obj.get("filename") or meta_obj.get("source") or meta_obj.get("title")
                        except Exception:
                            pass
                if not sha:
                    stats["skipped_no_hash"] += 1
                    continue
                filename = filename or row.get("title") or ""
                entry = {"ts": ts, "doc_id": str(doc_id), "filename": filename}
                try:
                    with self._cache_lock:
                        existed = sha in self._upsert_cache
                        self._upsert_cache[sha] = entry
                        os.makedirs(os.path.dirname(self._cache_path), exist_ok=True)
                        with open(self._cache_path, "w", encoding="utf-8") as fh:
                            json.dump(self._upsert_cache, fh)
                        stats["refreshed" if existed else "seeded"] += 1
                except Exception:
                    pass
                if max_rows is not None and stats["processed"] >= max_rows:
                    break

        logger.info(
            "Seeded upsert cache from export",
            extra={
                "processed": stats["processed"],
                "seeded": stats["seeded"],
                "refreshed": stats["refreshed"],
                "skipped_no_hash": stats["skipped_no_hash"],
                "cache_path": self._cache_path,
                "export_path": api_path,
            },
        )
        return stats

    # ------------------------------------------------------------------
    # Collections
    def ensure_collections(self, user_ids: Sequence[str]) -> dict[str, str]:
        offset, limit = 0, 100
        existing: dict[str, str] = {}
        while True:
            coll = self._request(
                "GET",
                "collections",
                action="ensure_collections:list",
                params={"offset": offset, "limit": limit},
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
                    action=f"ensure_collections:create:{uid}",
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
            "GET",
            "documents",
            action="list_documents",
            params={"offset": offset, "limit": limit},
        )
        return docs.get("results", [])

    def find_document_by_hash(self, sha256: str) -> dict | None:
        """Return document whose ``metadata.sha256`` matches ``sha256``.

        Use R2R's retrieval search with a wildcard query so that hash
        filtering happens server-side. Only a single result is requested,
        keeping the duplicate check effectively constant-time even for large
        collections.
        """
        try:
            resp = self._request(
                "POST",
                "retrieval/search",
                action="find_document_by_hash",
                json={
                    "query": "*",
                    "search_mode": "basic",
                    "search_settings": {
                        "filters": {"metadata.sha256": {"$eq": sha256}},
                        "limit": 1,
                    },
                },
            )
        except httpx.TimeoutException:
            logger.warning(
                "R2R find_document_by_hash timed out for %s; skipping duplicate check",
                sha256,
            )
            return None

        results = resp.get("results", {})
        if isinstance(results, list):
            hits: Sequence[Any] = results
        elif isinstance(results, dict):
            hits = results.get("chunk_search_results") or []
        else:
            hits = []

        for hit in hits:
            meta = hit.get("metadata", {}) if isinstance(hit, dict) else {}
            if meta.get("sha256") == sha256:
                return {"id": hit.get("document_id"), "metadata": meta}
        return None

    def find_document_by_title(self, title: str) -> dict | None:
        if not title:
            return None

        resp = self._request(
            "GET",
            "documents",
            action="find_document_by_title",
            params={
                "filters": json.dumps({"metadata.title": {"$eq": title}}),
                "limit": 1,
            },
        )
        for doc in resp.get("results", []) or []:
            meta_title = doc.get("metadata", {}).get("title") or doc.get("title")
            if meta_title == title:
                return doc
        return None

    def get_document(self, document_id: str) -> dict:
        """Return detailed information for a document.

        Some list queries omit fields such as ``ingestion_status``.  When we
        need authoritative metadata (e.g. to detect pending ingestions), fetch
        the document directly.
        """

        resp = self._request(
            "GET",
            f"documents/{document_id}",
            action=f"get_document:{document_id}",
        )
        return resp.get("results", {})

    def upsert_document(
        self,
        file_path: str,
        metadata: Mapping[str, Any],
        collection_ids: Sequence[str],
        *,
        precomputed_sha256: str | None = None,
    ) -> str:
        # Ensure cache structures are initialized (older builds may lack them in __init__)
        try:
            self._ensure_cache_setup()
        except Exception:
            pass
        if isinstance(collection_ids, str):
            raise ValueError("collection_ids must be a list of UUID strings")

        digest = precomputed_sha256
        if digest is None:
            with open(file_path, "rb") as fh:
                digest = hashlib.sha256(fh.read()).hexdigest()

        meta = dict(metadata)
        meta.setdefault("sha256", digest)
        title = meta.get("title", "")
        logger.info(
            "Checking if document '%s' exists with hash %s", title or "<no title>", digest
        )
        logger.debug(
            "Upsert skip windows",
            extra={
                "skip_all_secs": getattr(self, "_skip_all_within_secs", 0),
                "skip_meta_secs": getattr(self, "_skip_meta_within_secs", 0),
            },
        )

        # Fast-path 1: total skip within recent window since last upsert
        if getattr(self, "_skip_all_within_secs", 0) > 0:
            with self._cache_lock:
                entry = self._upsert_cache.get(str(digest), {}) if hasattr(self, "_upsert_cache") else None
            if entry and (time.time() - float(entry.get("ts", 0))) <= self._skip_all_within_secs:
                logger.info(
                    "Quick-skip all for '%s' (within %ss)",
                    title or "<no title>",
                    self._skip_all_within_secs,
                )
                # refresh timestamp to extend window
                try:
                    with self._cache_lock:
                        entry["ts"] = time.time()
                        self._upsert_cache[str(digest)] = entry
                        os.makedirs(os.path.dirname(self._cache_path), exist_ok=True)
                        with open(self._cache_path, "w", encoding="utf-8") as fh:
                            json.dump(self._upsert_cache, fh)
                except Exception:
                    pass
                cached_id = entry.get("doc_id") if isinstance(entry, dict) else None
                return str(
                    cached_id
                    or meta.get("filename")
                    or meta.get("source")
                    or title
                    or os.path.basename(file_path)
                )

        # Fast-path 2: skip metadata checks within meta window if hash unchanged
        if getattr(self, "_skip_meta_within_secs", 0) > 0:
            with self._cache_lock:
                entry2 = self._upsert_cache.get(str(digest), {}) if hasattr(self, "_upsert_cache") else None
            if entry2 and (time.time() - float(entry2.get("ts", 0))) <= self._skip_meta_within_secs:
                logger.info(
                    "Quick-skip meta for '%s' (within %ss; hash unchanged)",
                    title or "<no title>",
                    self._skip_meta_within_secs,
                )
                try:
                    with self._cache_lock:
                        entry2["ts"] = time.time()
                        self._upsert_cache[str(digest)] = entry2
                        os.makedirs(os.path.dirname(self._cache_path), exist_ok=True)
                        with open(self._cache_path, "w", encoding="utf-8") as fh:
                            json.dump(self._upsert_cache, fh)
                except Exception:
                    pass
                cached_id2 = entry2.get("doc_id") if isinstance(entry2, dict) else None
                return str(
                    cached_id2
                    or meta.get("filename")
                    or meta.get("source")
                    or title
                    or os.path.basename(file_path)
                )

        # Skip early if extension is configured to be excluded locally
        try:
            filename_for_ext = metadata.get("filename") or os.path.basename(file_path)
        except Exception:
            filename_for_ext = os.path.basename(file_path)
        _, ext = os.path.splitext(str(filename_for_ext))
        if ext:
            ext = ext.lower()
        if ext and ext in self._excluded_exts:
            logger.info(
                "Skipping upload for '%s' due to excluded extension '%s'",
                title or "<no title>",
                ext,
            )
            # Return a benign identifier so the client proceeds. Prefer the
            # source/filename identifier used by Nextcloud where available.
            return str(metadata.get("filename") or metadata.get("source") or title or filename_for_ext)

        # Best-effort backpressure gate: if downstream queues appear overloaded,
        # signal a retry to the caller rather than proceeding with ingestion.
        # Backpressure gate with optional wait window
        try:
            max_wait = 0.0
            try:
                max_wait = float(os.getenv("R2R_MAX_WAIT_SECONDS", os.getenv("QUEUE_MAX_WAIT_SECONDS", "0") or 0))
            except Exception:
                max_wait = 0.0
            start_wait = time.time()
            while True:
                ok = True
                try:
                    ok = self.can_accept_ingestion()
                except Exception:
                    ok = True
                if ok:
                    break
                if max_wait <= 0 or (time.time() - start_wait) >= max_wait:
                    retry_id = str(
                        metadata.get("filename")
                        or metadata.get("source")
                        or title
                        or os.path.basename(file_path)
                    )
                    raise RetryableBackendBusy(
                        "R2R busy; please retry shortly",
                        payload={"sources_to_retry": [retry_id]},
                    )
                time.sleep(0.5)
        except RetryableBackendBusy:
            raise
        except Exception:
            # Do not block on probe errors
            pass

        doc_by_hash = self.find_document_by_hash(digest)
        if doc_by_hash and doc_by_hash.get("metadata", {}).get("sha256") == digest:
            logger.info(
                "Document '%s' exists with same hash; verifying metadata and collections",
                title or "<no title>",
            )
            logger.info(
                "Retrieving document '%s' details for comparison (id %s)",
                title or "<no title>",
                doc_by_hash["id"],
            )
            existing = None
            try:
                existing = self.get_document(doc_by_hash["id"])
            except httpx.HTTPStatusError as exc:  # type: ignore[name-defined]
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status == 404:
                    # Retrieval search returned a stale id; treat as not found and fall through
                    logger.info(
                        "Document id %s not found by GET; treating as not found-by-hash",
                        doc_by_hash["id"],
                    )
                    existing = None
                else:
                    raise

            if existing is not None:
                em = existing.get("metadata", {})
                if em != meta:
                    meta_list = [
                        {"key": key, "value": value} for key, value in meta.items()
                    ]
                    self._request(
                        "PUT",
                        f"documents/{existing['id']}/metadata",
                        action=f"upsert_document:update_metadata:{existing['id']}",
                        desc=f"Updating metadata for document '{title}' ({existing['id']})",
                        json=meta_list,
                    )
                current = set(existing.get("collection_ids", []))
                target = set(collection_ids)
                add = target - current
                rem = current - target
                for cid in add:
                    self._request(
                        "POST",
                        f"collections/{cid}/documents/{existing['id']}",
                        action=f"upsert_document:add:{existing['id']}:{cid}",
                        desc=(
                            f"Adding document '{title}' ({existing['id']}) to collection {cid}"
                        ),
                    )
                for cid in rem:
                    self._request(
                        "DELETE",
                        f"collections/{cid}/documents/{existing['id']}",
                        action=f"upsert_document:remove:{existing['id']}:{cid}",
                        desc=(
                            f"Removing document '{title}' ({existing['id']}) from collection {cid}"
                        ),
                    )
                # Update cache timestamp and id for future skip windows
                try:
                    with self._cache_lock:
                        self._upsert_cache[str(digest)] = {
                            "ts": time.time(),
                            "doc_id": existing["id"],
                            "filename": meta.get("filename", ""),
                        }
                        os.makedirs(os.path.dirname(self._cache_path), exist_ok=True)
                        with open(self._cache_path, "w", encoding="utf-8") as fh:
                            json.dump(self._upsert_cache, fh)
                except Exception:
                    pass
                return existing["id"]

        logger.info(
            "Document '%s' not found by hash; checking by title", title or "<no title>"
        )
        existing_stub = self.find_document_by_title(title)
        if existing_stub:
            logger.info(
                "Retrieving document '%s' details for hash comparison (id %s)",
                title or "<no title>",
                existing_stub["id"],
            )
            existing = None
            try:
                existing = self.get_document(existing_stub["id"])
            except httpx.HTTPStatusError as exc:  # type: ignore[name-defined]
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status == 404:
                    logger.info(
                        "Title match id %s not found; proceeding to create new document",
                        existing_stub["id"],
                    )
                    existing = None
                else:
                    raise

            if existing is not None:
                ingestion_status = existing.get("ingestion_status") or existing.get("status")
                if ingestion_status and ingestion_status != "success":
                    logger.info(
                        "Document '%s' (id %s) ingestion pending; reusing", title, existing["id"]
                    )
                    # Update cache timestamp and id for future skip windows
                    try:
                        with self._cache_lock:
                            self._upsert_cache[str(digest)] = {
                                "ts": time.time(),
                                "doc_id": existing["id"],
                                "filename": meta.get("filename", ""),
                            }
                            os.makedirs(os.path.dirname(self._cache_path), exist_ok=True)
                            with open(self._cache_path, "w", encoding="utf-8") as fh:
                                json.dump(self._upsert_cache, fh)
                    except Exception:
                        pass
                    return existing["id"]
                logger.info(
                    "Document '%s' exists but hash value has changed; deleting old version to upsert new version",
                    title or "<no title>",
                )
                # Title matches but hash differs, so replace the existing document.
                self.delete_document(existing["id"], title=title)

        with open(file_path, "rb") as fh:
            # ``mimetypes.guess_type`` relies on file extensions.  The sanitized
            # ``meta['filename']`` often lacks one, so use the temporary file
            # path (which preserves the original extension) to determine the
            # content type.  ``meta`` may optionally include an explicit
            # ``type``; if guessing fails, fall back to that before using the
            # generic ``application/octet-stream``.
            mime, _ = mimetypes.guess_type(os.path.basename(file_path))
            if not mime:
                mime = meta.get("type")

            filename = meta.get("filename")
            if not filename or not os.path.splitext(filename)[1]:
                filename = os.path.basename(file_path)

            files = [
                (
                    "file",
                    (
                        filename,
                        fh,
                        mime or "application/octet-stream",
                    ),
                ),
                ("metadata", (None, json.dumps(meta), "application/json")),
                (
                    "collection_ids",
                    (None, json.dumps(list(collection_ids)), "application/json"),
                ),
                ("ingestion_mode", (None, "custom")),
                ("run_with_orchestration", (None, "true")),
            ]
            # Increase in-flight upserts while performing the create call
            with self._metrics_lock:
                self._inflight_upserts += 1
            try:
                created = self._request(
                    "POST",
                    "documents",
                    action="upsert_document:create",
                    desc=f"Creating new document '{title}'",
                    files=files,
                )
            except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadTimeout):
                # Upstream overloaded or network hiccup — instruct caller to retry
                retry_id = str(
                    metadata.get("filename")
                    or metadata.get("source")
                    or title
                    or filename
                )
                raise RetryableBackendBusy(
                    "R2R timed out during ingestion; please retry",
                    payload={"sources_to_retry": [retry_id]},
                )
            except httpx.HTTPStatusError as exc:
                # Gracefully handle R2R-side exclusions (e.g., blocked by
                # ga_r2r.toml rules). Common signals observed:
                # - 413 with message like "File size exceeds maximum of 0 bytes for extension 'xlsx'."
                # - 400/415 style validation errors for disallowed types
                status = getattr(getattr(exc, "response", None), "status_code", None)
                body = ""
                try:
                    body = exc.response.text  # type: ignore[assignment]
                except Exception:
                    body = str(exc)

                lower = (body or "").lower()
                signals = (
                    "0 bytes for extension" in lower
                    or "exceeds maximum" in lower
                    or "not a valid documenttype" in lower
                    or "disallowed extension" in lower
                )
                if status in {400, 413, 415, 422} and signals:
                    logger.info(
                        "R2R rejected '%s' (ext '%s') by config; skipping",
                        title or filename_for_ext,
                        ext or "",
                    )
                    return str(
                        metadata.get("filename")
                        or metadata.get("source")
                        or title
                        or filename_for_ext
                    )
                # If R2R reports upstream busy/gateway issues, make it retryable
                if status in {502, 503, 504}:
                    retry_id2 = str(
                        metadata.get("filename")
                        or metadata.get("source")
                        or title
                        or filename
                    )
                    raise RetryableBackendBusy(
                        "Upstream R2R busy; please retry",
                        payload={"sources_to_retry": [retry_id2]},
                    )
                raise
            finally:
                try:
                    with self._metrics_lock:
                        self._inflight_upserts = max(0, self._inflight_upserts - 1)
                except Exception:
                    pass
        doc_id = created.get("results", {}).get("document_id", "")
        # Update cache on successful create so reruns can skip quickly
        try:
            with self._cache_lock:
                self._upsert_cache[str(digest)] = {
                    "ts": time.time(),
                    "doc_id": doc_id,
                    "filename": meta.get("filename", ""),
                }
                os.makedirs(os.path.dirname(self._cache_path), exist_ok=True)
                with open(self._cache_path, "w", encoding="utf-8") as fh:
                    json.dump(self._upsert_cache, fh)
        except Exception:
            pass
        return doc_id

    def find_document_by_filename(self, filename: str) -> dict | None:
        if not filename:
            return None

        resp = self._request(
            "GET",
            "documents",
            action="find_document_by_filename",
            params={
                "filters": json.dumps({"metadata.filename": {"$eq": filename}}),
                "limit": 1,
            },
        )
        for doc in resp.get("results", []) or []:
            meta_filename = (
                doc.get("metadata", {}).get("filename")
                or doc.get("metadata", {}).get("title")
                or doc.get("title")
            )
            if meta_filename == filename:
                return doc
        return None

    def delete_document(self, document_id: str, *, title: str | None = None) -> None:
        """
        Delete a document by its R2R UUID. If a non-UUID value is provided
        (e.g. a Context Chat "source id" like ``files__default:123``), resolve
        it by filename first and then delete by the resolved UUID.
        """
        # Accept CCBE-style source ids by resolving to the actual R2R document id
        try:
            uuid.UUID(str(document_id))
            resolved_id = document_id
        except ValueError:
            # Fall back to deletion by filename/source identifier
            self.delete_document_by_filename(document_id)
            return

        desc = f"Deleting document {resolved_id}"
        if title:
            desc += f" ('{title}')"
        self._request(
            "DELETE",
            f"documents/{resolved_id}",
            action=f"delete_document:{resolved_id}",
            desc=desc,
        )

    def delete_document_by_filename(self, filename: str) -> None:
        doc = self.find_document_by_filename(filename)
        if doc:
            self.delete_document(doc["id"], title=filename)

    # ------------------------------------------------------------------
    # Access control helpers
    def update_access(
        self,
        op: UpdateAccessOp,
        user_ids: Sequence[str],
        document_id: str,
    ) -> None:
        mapping = self.ensure_collections(user_ids)
        for cid in mapping.values():
            try:
                if op is UpdateAccessOp.allow:
                    self._request(
                        "POST",
                        f"collections/{cid}/documents/{document_id}",
                        action=f"update_access:allow:{document_id}:{cid}",
                    )
                else:
                    self._request(
                        "DELETE",
                        f"collections/{cid}/documents/{document_id}",
                        action=f"update_access:deny:{document_id}:{cid}",
                    )
            except httpx.HTTPStatusError as exc:  # ignore idempotent errors
                if exc.response.status_code not in {404, 409}:
                    raise

    def decl_update_access(
        self, user_ids: Sequence[str], document_id: str
    ) -> None:
        mapping = self.ensure_collections(user_ids)
        existing = self._request(
            "GET",
            f"documents/{document_id}/collections",
            action=f"decl_update_access:list:{document_id}",
        ).get("results", [])
        current = {c.get("name", ""): c.get("id", "") for c in existing}
        target = set(mapping.keys())
        for name, cid in mapping.items():
            if name not in current:
                self._request(
                    "POST",
                    f"collections/{cid}/documents/{document_id}",
                    action=f"decl_update_access:add:{document_id}:{cid}",
                )
        for name, cid in current.items():
            if name not in target:
                self._request(
                    "DELETE",
                    f"collections/{cid}/documents/{document_id}",
                    action=f"decl_update_access:remove:{document_id}:{cid}",
                )

    # ------------------------------------------------------------------
    # Retrieval (minimal shape)
    def rag(
        self,
        *,
        user_id: str,
        query: str,
        ctx_limit: int,
        scope_type: str | None = None,
        scope_list: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """Call R2R RAG endpoint and return answer + hits.

        Returns a dict with keys:
        - answer: str | None
        - hits: list[dict] (chunk hits with page_content + metadata)
        """
        payload: dict[str, Any] = {"query": query, "top_k": ctx_limit}
        payload["filters"] = {"collection_ids": {"$overlap": [user_id]}}
        if scope_type and scope_list:
            payload["scope"] = {"type": scope_type, "ids": list(scope_list)}
        logger.debug("R2R search payload: %s", json.dumps(payload, sort_keys=True))
        try:
            resp = self._request(
                "POST", "retrieval/rag", action="/v3/retrieval/rag", json=payload
            )
        except httpx.HTTPError as exc:
            logger.warning("rag request failed", extra={"error": str(exc)})
            return {"answer": None, "hits": []}

        rag_results = resp.get("results", {})
        answer = None
        if isinstance(rag_results, dict):
            answer = rag_results.get("generated_answer") or rag_results.get("answer")
        # Pluggable control: if disabled via env, force fallback to local LLM
        try:
            prefer = os.getenv("R2R_USE_GENERATED_ANSWER", "true").lower() in {"1", "true", "yes"}
        except Exception:
            prefer = True
        if not prefer:
            answer = None

        # Normalize hits similar to search()
        results = rag_results.get("search_results") if isinstance(rag_results, dict) else {}
        if isinstance(results, list):
            hits_src: Sequence[Any] = results
        elif isinstance(results, dict):
            hits_src = results.get("chunk_search_results") or []
        else:
            hits_src = []

        hits: list[dict[str, Any]] = []
        for hit in hits_src:
            if isinstance(hit, str):
                hits.append({"page_content": hit, "metadata": {}})
            else:
                hits.append(
                    {
                        "page_content": hit.get("text") or hit.get("content", ""),
                        "metadata": hit.get("metadata", {}),
                    }
                )

        logger.debug(
            "R2R rag results",
            extra={
                "has_answer": bool(answer),
                "hits": hits,
            },
        )
        return {"answer": answer, "hits": hits}

    def search(
        self,
        user_id: str,
        query: str,
        ctx_limit: int,
        scope_type: str | None = None,
        scope_list: Sequence[str] | None = None,
    ) -> list[dict]:
        payload: dict[str, Any] = {"query": query, "top_k": ctx_limit}
        payload["filters"] = {"collection_ids": {"$overlap": [user_id]}}
        if scope_type and scope_list:
            payload["scope"] = {"type": scope_type, "ids": list(scope_list)}
        logger.debug("R2R search payload: %s", json.dumps(payload, sort_keys=True))
        rag = self.rag(
            user_id=user_id,
            query=query,
            ctx_limit=ctx_limit,
            scope_type=scope_type,
            scope_list=scope_list,
        )
        out = rag.get("hits", [])
        logger.debug("R2R search results: %s", json.dumps(out, ensure_ascii=False))
        return out

    def config(self) -> dict[str, Any]:
        return {
            "base_url": self._base_url,
            "auth": {
                "api_key": self._has_api_key,
                "token": self._has_token,
            },
        }


# Backwards compatibility for earlier imports
R2RBackend = R2rBackend
