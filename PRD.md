# PRD — Pluggable RAG backends for Nextcloud Context Chat Backend (CCBE), defaulting to R2R

## 1) Overview

**Problem**
CCBE today bundles retrieval/storage logic tightly to a specific vector DB path, often in-process with the backend. We want a fork that supports a *pluggable* Retrieval-Augmented Generation (RAG) backend that can run independently—possibly in its own container or an existing DB with a CCBE schema—and is selected and connected via `.env`, while keeping a very small, reviewable diff from upstream so maintainers can adopt it.

**Proposal**
Introduce a thin **backend adapter interface** and one concrete implementation for the **R2R Graph RAG** backend (default), plus scaffolding for **pgvector**, **Pinecone**, and **Supabase**. Retain all existing CCBE endpoint contracts. Selection and connection details come from environment variables so the RAG database can live at arm's length. Code paths stay minimal and isolated.

**Non-goals**

* No UI changes in Nextcloud.
* No breaking changes to existing CCBE HTTP endpoints or request/response payloads.
* No deviation from AppAPI handshake & lifecycle semantics.

---

## 2) Goals & Success Criteria

### Functional goals

1. **Backend selection via env**

   * `.env`: `RAG_BACKEND=r2r|pgvector|pinecone|supabase`
   * Default: `r2r`.
2. **Arms-length storage**

   * RAG database runs independently (e.g., separate container or existing DB schema) and CCBE connects using `.env` connection details.
3. **Drop-in adoption**

   * Upstream endpoint paths, headers, and status codes remain identical.
   * Code changes localized; fork can be rebased easily.
4. **R2R working E2E** (fast path)

   * Registration succeeds (`/enabled`, `/heartbeat`, `/init` semantics respected`).
   * `/loadSources` ingests files into R2R collections keyed by user IDs.
   * `/query` returns answers using retrieved context from the selected backend.
5. **Plugin architecture**

   * Backends implement a common interface (detailed below).
   * New providers can be added by dropping in a module.

### Non-functional goals

* Clear logging (debuggable in container logs).
* Minimal new dependencies (R2R client lib only, others optional).
* Keep diffs small: new `backends/` folder + tiny wiring changes.
* Document all endpoints & plugin contract inline in repo.

### Acceptance criteria

* Registration log shows: `PUT /enabled?enabled=1` → 200, `POST /init` → 200 (empty `{}`), background progress hits 100.
* Uploading sources logs “Document created with ID …” and **does not** split collection UUIDs into characters.
* Switching `RAG_BACKEND=pgvector` keeps the app booting; unimplemented methods raise friendly “not implemented” with 501 (until fully implemented).
* Diff to upstream is small and easy to review.

---

## 3) Architecture

### 3.1 New module layout

```
context_chat_backend/
  backends/
    base.py            # abstract interface
    r2r.py             # R2R Graph RAG implementation (default)
    pgvector_adapter.py  # thin adapter over existing vector flow
    pinecone.py        # scaffold
    supabase.py        # scaffold
```

### 3.2 Backend adapter interface

```python
# backends/base.py
from typing import Any, Iterable, Mapping, Sequence

class RagBackend:
    # Collections / tenancy
    def ensure_collections(self, user_ids: Sequence[str]) -> dict[str, str]:
        """Ensure per-user collections; return {user_id: collection_id}."""

    # Documents
    def find_document_by_title(self, title: str) -> dict | None:
        """Return provider's doc object (id, metadata, collection_ids…), else None."""

    def upsert_document(
        self,
        file_path: str,
        metadata: Mapping[str, Any],
        collection_ids: Sequence[str]
    ) -> str:
        """Create or replace; return document_id."""

    def delete_document(self, document_id: str) -> None: ...

    def list_documents(self, offset: int = 0, limit: int = 100) -> list[dict]: ...

    # Retrieval
    def search(
        self,
        user_id: str,
        query: str,
        ctx_limit: int,
        scope_type: str | None = None,
        scope_list: Sequence[str] | None = None,
    ) -> list[dict]:
        """Return ranked docs/chunks with text + metadata."""
```

### 3.3 Backend selection

* At startup (in `main.py`), read `RAG_BACKEND` and instantiate the matching adapter; store it as `app.state.rag_backend`.
* Controller endpoints call `request.app.state.rag_backend`.

### 3.4 Minimal diffs strategy

* **Do not** change existing route paths or shapes.
* Add only:

  * The new `backends/` package.
  * A small initialization block in `main.py`.
  * Small substitutions in controller where we currently touch vectordb/ingest/search—call the adapter instead.
* Keep middleware and guards identical in behavior.

---

## 4) R2R backend details (default)

### 4.1 Env & config

```
RAG_BACKEND=r2r
R2R_BASE_URL=http://127.0.0.1:7272
```

### 4.2 Collections policy

* Map **user IDs** (from `UploadFile.headers['userIds']`) to R2R collections with `ensure_collections()`.
* **Important lesson**: treat `userIds` as a **comma-separated string** → split to a **list of strings**.

### 4.3 Document upsert semantics

* If a document with the same `title` exists:

  * Compare `metadata.modified` and `metadata.content-length`. If identical → no re-ingest; only **fix collection membership** (add/remove).
  * If different → delete and recreate.
* **Important lesson**: pass `collection_ids` as a **list of UUID strings**, **not** a comma-joined string. (Passing a string leads to per-character UUID parsing errors.)
* Create via temp file preserving extension; use `ingestion_mode="fast"`.

### 4.4 Retrieval

* `search()` queries R2R returning text + metadata.
* Return simplest shape needed by upstream context assembly (title, page_content, metadata).

---

## 5) Other providers (scaffolds)

### 5.1 pgvector

* Adapter wraps existing CCBE vectordb/search calls.
* Env:

  ```
  RAG_BACKEND=pgvector
  CCB_DB_URL=postgresql+psycopg://user:pass@host:port/db
  ```
* Implement: ensure_collections (collection per user), upsert (embedding flow unchanged), search.

### 5.2 Pinecone / Supabase

* Provide **skeletons** with clear `NotImplementedError` and env keys:

  ```
  RAG_BACKEND=pinecone
  PINECONE_API_KEY=...
  PINECONE_INDEX=...
  ```

  ```
  RAG_BACKEND=supabase
  SUPABASE_URL=...
  SUPABASE_ANON_KEY=...
  ```
* Endpoint behavior: return 501 with `"backend not implemented"` if selected without complete implementation.

---

## 6) Endpoints (document & keep stable)

> All endpoints must keep existing paths, auth headers, and content shapes. Add docstrings and README endpoint docs.

1. `GET /heartbeat`

   * Returns `200 OK` plain `"OK"`.
   * Purpose: AppAPI health check.

2. `GET /`

   * Debug root; unchanged.

3. `GET /enabled`

   * Returns `{"enabled": bool}`; used by AppAPI to check readiness.

4. `PUT /enabled?enabled=0|1`

   * Toggle app enabled state.
   * **Lesson**: use `fastapi.Query` for the param, not a Pydantic model named `Query` (name collision). E.g.:

     ```python
     from fastapi import Query as FQuery

     def set_enabled(enabled: int = FQuery(1)): ...
     ```

5. `POST /init`

   * **Return immediately** with `{}` and `200`.
   * Spawn background job:

     * Validate backend connectivity (e.g., `client.system.settings()` for R2R).
     * Warm caches (optional).
     * **Report progress** via OCS `PUT /ocs/v1.php/apps/app_api/ex-app/status` (values 1–100; include `"error"` if fatal).

       * **Lesson**: Do not block this endpoint; 404/501 also acceptable per AppAPI, but we’ll implement it cleanly.

6. `PUT /loadSources`

   * Multipart files with headers:

     * `userIds` (comma-separated), `title`, `modified`, `provider`, `content-length`.
   * For each `UploadFile`:

     * Parse `userIds` → list.
     * `ensure_collections(user_ids)` → `collection_ids`.
     * Check `find_document_by_title(title)`.
     * Upsert with `collection_ids` **list**, not string.
     * Return array of created/updated document IDs.
   * **Guarded by enabled state**.

7. `/query` (POST)

   * Unchanged schema. Adapter `.search()` feeds context; LLM generation path unchanged.

8. Any delete/update-access endpoints present upstream

   * Rewire to adapter (`delete_document`, collection membership operations).

---

## 7) Middleware & lifecycle

* Keep `VersionHeaderMiddleware` that sets `EX-APP-VERSION` from `APP_VERSION` env.
* Add middleware in `main.py` **once** (avoid double-adding in `controller.py`).
* Respect and log AppAPI headers (`aa-version`, `ex-app-id`, etc.) for traceability.

---

## 8) Config & Environment

Backends receive connection strings, URLs, and credentials via environment variables so CCBE can talk to databases running outside of the application container.

Example `.env`:

```
APP_VERSION=4.0.2
NEXTCLOUD_URL=http://your-nc:8080
RAG_BACKEND=r2r

# R2R
R2R_BASE_URL=http://127.0.0.1:7272

# pgvector (if used)
CCB_DB_URL=postgresql+psycopg://root:rootpassword@localhost:4445/nextcloud

# pinecone (scaffold)
PINECONE_API_KEY=
PINECONE_INDEX=

# supabase (scaffold)
SUPABASE_URL=
SUPABASE_ANON_KEY=
```

---

## 9) Error handling & logging

* Wrap adapter calls; surface concise errors to clients, detailed traces to logs.
* **Lessons baked in**:

  * If `collection_ids` is a string → raise a clear `400` with `"collection_ids must be a list of UUID strings"`.
  * If Pydantic validation fails for params → return the validation detail rather than crashing the server.
* Log request headers at debug level for `/heartbeat`, `/init`, `/enabled`, `/loadSources` to aid AppAPI integration debugging.

---

## 10) Security

* Only Nextcloud should call these endpoints; keep existing auth header checks/guards.
* No credentials logged.
* Large files: stream to temp files, close handles reliably.

---

## 11) Testing plan

1. **Unit tests**

   * Adapter selection from env.
   * R2R `ensure_collections` (new vs existing).
   * Upsert behavior (no-op vs re-ingest based on metadata).
   * `collection_ids` type safety (list required).
2. **Integration (local)**

   * Simulate AppAPI flow: `GET /heartbeat` → `PUT /enabled` → `POST /init` (verify background progress reaches 100).
   * `/loadSources`: upload with headers; verify creation, re-upload idempotency.
   * `/query`: sanity run.
3. **Regression**

   * Verify renaming of request models avoids FastAPI `Query` collisions.
   * Verify `VersionHeaderMiddleware` appears on all responses.

---

## 12) Developer guidance for minimal diff

* **Do**:

  * Add `backends/` package.
  * In `main.py`:

    * Instantiate adapter based on `RAG_BACKEND`.
    * Add `VersionHeaderMiddleware`.
    * Include router as upstream does.
  * In controller:

    * Replace direct vectordb / ingest calls with adapter calls at seam points.
    * Keep function signatures and routes identical.
* **Don’t**:

  * Move or rename existing endpoints.
  * Change response shapes.
  * Add global side effects in adapter modules.

---

## 13) Implementation notes (from practical lessons)

* **Init**: per AppAPI docs, return `{}` immediately and send progress asynchronously; accept that AppAPI considers 404/501 as “skip,” but we implement a proper `200 {}`.
* **Enabled**: parse `enabled` via `fastapi.Query` to avoid Pydantic model collisions (`Query` name clash).
* **Upload**: `userIds` header → split on commas; pass **list** of collection IDs to provider SDKs (R2R included).
* **Temp files**: preserve file extension for R2R content type inference.
* **R2R health**: call `client.system.settings()` at startup to fail fast if unreachable.
* **Don’t add middleware in `controller.py`**; add it **once** in `main.py`.
* **Keep EX-APP-VERSION** on every response.

---

## 14) Rollout & timeline

* **Day 1–2**: Add `backends/` base + R2R adapter; env selection; wire up ingest/search seams.
* **Day 3**: Implement `/init` progress worker; finalize `/enabled` semantics; logging.
* **Day 4**: Write tests; docs for all endpoints and plugin interface.
* **Day 5**: Manual E2E with Nextcloud AppAPI register/unregister cycle; open PR (small diff).

---

## 15) Open questions

* Should we persist a mapping of `title → document_id` locally to avoid paging through provider lists? (R2R call may be paginated.)
* For R2R search, do we want per-chunk versus full-doc retrieval? (MVP: whatever R2R returns that is simplest to pipe to existing context assembly.)
* Any quota/backoff policies needed for large batch ingestions?

---

## 16) Documentation deliverables (in-repo)

* `README.md`:

  * How to choose a backend via `.env`.
  * R2R quick start.
  * Endpoint reference (paths, methods, headers, sample requests/responses).
  * Plugin authoring guide (how to add a new backend).
* Inline docstrings on adapter methods and endpoints.

---

## 17) Example snippets

### Selecting backend (main.py)

```python
import os
from fastapi import FastAPI
from .middleware import VersionHeaderMiddleware
from .controller import router
from .backends.r2r import R2RBackend
from .backends.pgvector_adapter import PgVectorBackend
# from .backends.pinecone import PineconeBackend
# from .backends.supabase import SupabaseBackend

def build_backend(kind: str):
    match (kind or "r2r").lower():
        case "r2r": return R2RBackend()
        case "pgvector": return PgVectorBackend()
        case "pinecone": raise NotImplementedError("pinecone backend not implemented")
        case "supabase": raise NotImplementedError("supabase backend not implemented")
        case _: raise ValueError(f"Unknown RAG_BACKEND: {kind}")

app = FastAPI()
app.add_middleware(VersionHeaderMiddleware)
app.state.rag_backend = build_backend(os.getenv("RAG_BACKEND", "r2r"))
app.include_router(router)
```

### Using adapter in `/loadSources` (controller seam)

```python
backend = request.app.state.rag_backend
user_ids = [u.strip() for u in source.headers["userIds"].split(",") if u.strip()]
mapping = backend.ensure_collections(user_ids)
collection_ids = list(mapping.values())  # list, not string!

# upsert via temp file
doc_id = backend.upsert_document(temp_path, metadata, collection_ids)
```

---

This PRD gives the codex agents a clear map: keep the surface stable, add a tiny, well-defined plugin seam, make R2R the default and production-ready, and capture the specific pitfalls we hit (init semantics, FastAPI `Query` collision, and the `collection_ids` list vs string bug) so we reach a working R2R build fast with minimal churn.
