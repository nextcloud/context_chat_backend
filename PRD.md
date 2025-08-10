Got it—here’s a cleaned-up PRD that (1) keeps **CCBE’s current/built-in RAG path as the default and first-class**, (2) adds a **pluggable backend seam** with minimal diffs, and (3) documents an **exhaustive, test-verified endpoint surface** so every Nextcloud AppAPI call is handled regardless of backend. I’ve folded in the hard-earned lessons from your bring-up (init semantics, `Query` clash, `collection_ids` type, etc.) and made sure the “swap to R2R (or others)” path is simple, env-driven, and diff-friendly.

---

# PRD — Pluggable RAG backends for Nextcloud Context Chat Backend (CCBE)

### Default = **current built-in backend** (upstream), optional adapters: **R2R**, Pinecone, Supabase

## 1) Overview

**Problem**
CCBE’s retrieval/storage is currently tied to a single in-tree path. We want a fork that introduces a *thin, optional* backend adapter layer so maintainers can keep the default behavior intact, while enabling users to point CCBE at an external RAG backend (e.g., **Sciphi R2R** graph RAG, Pinecone, Supabase, etc.) by **.env** only. Diffs to upstream should be small and obvious to maximize adoption.

**Approach**

* Add a **RAG backend interface** (one file) and **adapters** (one module per provider).
* **Default to the built-in upstream backend** (no behavior change).
* Include a production-ready **R2R adapter** (opt-in via env).
* Keep **all HTTP endpoints identical**; only the data-layer calls are swapped.

**Non-goals**

* No UI changes.
* No breaking changes to payloads or status codes.
* No deviation from Nextcloud **AppAPI** lifecycle.

---

## 2) Goals & Success Criteria

### Functional

1. **Zero change by default**

   * If `RAG_BACKEND` is unset or `builtin`, CCBE behaves exactly as upstream (built-in backend path).

2. **Env-selectable backend**

   * `.env`: `RAG_BACKEND=builtin|r2r|pinecone|supabase`
   * Each backend reads its own connection/env vars.

3. **Full endpoint parity**

   * Every existing CCBE endpoint keeps method, path, parameters, and response shape.
   * **Exhaustive** docs generated at build/test time from FastAPI router (see §6 + §9).

4. **R2R: fast working path**

   * `/enabled`, `/heartbeat`, `/init` behave per AppAPI.
   * `/loadSources` ingests to **R2R collections keyed by user IDs**, no per-character UUID bugs.
   * `/query` returns answers using retrieved context from R2R.

5. **Plugin architecture**

   * Backends implement one interface; swapping is wiring-only.

### Non-functional

* Minimal new deps (R2R client optional).
* Clear logs for AppAPI handshakes & ingestion.
* Small, reviewable diff.

### Acceptance

* Unset/`builtin`: identical behavior to upstream (spot-check endpoints).
* `r2r`: E2E succeeds (registration, ingest, query).
* Unimplemented adapters return **501** with a friendly message.
* Auto-doc job emits the **complete** endpoint list (used in tests).

---

## 3) Architecture

```
context_chat_backend/
  backends/
    base.py              # abstract interface (tiny)
    builtin_pgvector.py  # wraps current upstream storage/retrieval (default)
    r2r.py               # Sciphi R2R adapter (opt-in)
    pinecone.py          # scaffold
    supabase.py          # scaffold
```

### Backend interface (single seam)

```python
# backends/base.py
from typing import Any, Mapping, Sequence

class RagBackend:
    # Collections / tenancy
    def ensure_collections(self, user_ids: Sequence[str]) -> dict[str, str]:
        """Ensure per-user collections; return {user_id: collection_id}."""

    # Documents
    def list_documents(self, *, offset: int = 0, limit: int = 100) -> list[dict]: ...
    def find_document_by_title(self, title: str) -> dict | None: ...
    def delete_document(self, document_id: str) -> None: ...
    def upsert_document(
        self,
        file_path: str,
        metadata: Mapping[str, Any],
        collection_ids: Sequence[str],     # IMPORTANT: list, not comma-joined string
    ) -> str:                              # returns document_id
        ...

    # Retrieval
    def search(
        self,
        *,
        user_id: str,
        query: str,
        ctx_limit: int,
        scope_type: str | None = None,
        scope_list: Sequence[str] | None = None,
    ) -> list[dict]:  # [{text, score, metadata, doc_id, ...}]
        ...
```

### Backend selection (startup)

* In `main.py`, read `RAG_BACKEND` and create the adapter once:

  * `builtin` → `BuiltinBackend()` (wraps current code paths).
  * `r2r` → `R2RBackend()`.
  * others → scaffolds (501).
* Store as `app.state.rag_backend`.

**Diff strategy:** only add `backends/` + small glue in `main.py` and at the current data-layer touch points in `controller.py`. No route shape changes.

---

## 4) R2R adapter specifics (opt-in)

**Env**

```
RAG_BACKEND=r2r
R2R_BASE_URL=http://127.0.0.1:7272
```

**Lessons baked in**

* Parse `UploadFile.headers['userIds']` as a **comma-separated list** of user IDs; trim empties.
* `ensure_collections()` maps each userId → an R2R collection; returns a dict; use its **values** (UUIDs) as `collection_ids`.
* **Pass `collection_ids` as a list of UUID strings** to the create/upsert call.
  *Do not* pass a single comma-joined string (causes per-character UUID parse errors).
* Upsert policy:

  * If a doc with the same `title` exists:

    * If `modified` *and* `content-length` match → no re-ingest; just **reconcile collection membership** (add/remove).
    * Otherwise delete and recreate.
* For health checks, call `client.system.settings()` once at startup or in `/init` worker; surface clear errors.

---

## 5) Built-in backend (default)

* The **default** remains the current upstream storage/retrieval implementation (“builtin\_pgvector” here), wrapped in `BuiltinBackend` so routes don’t change.
* No behavior changes when `RAG_BACKEND` is unset/`builtin`.
* This keeps maintainers comfortable and makes the diff easy to accept.

---

## 6) Endpoint surface (exhaustive & stable)

> Keep all methods, paths, params, and payloads **unchanged**.
> Below is the **canonical list** + a **test-verified generator** (see §9) that extracts the router table at build time to guarantee completeness. If the app has more endpoints than listed, the CI will fail until docs include them.

### 6.1 Liveness & lifecycle (AppAPI)

1. `GET /heartbeat` → `200 "OK"`
   Health probe used by AppAPI.

2. `GET /` → existing root → unchanged (debug/info).

3. `GET /enabled` → `{"enabled": bool}`
   Returns current enabled state.

4. `PUT /enabled?enabled=0|1` → `200 {"enabled": bool}`
   Toggle enabled state.
   **Pitfall fixed:** use `from fastapi import Query as FQuery` to avoid name clash with Pydantic `Query`.

5. `POST /init` → **return immediately** with `{}` and `200`
   Start a background worker that:

   * Verifies backend connectivity.
   * Reports progress to Nextcloud via `PUT /ocs/v1.php/apps/app_api/ex-app/status` with `{"progress": 1..100}`; include `{"error": "..."}`
     if fatal. Don’t block the endpoint.

### 6.2 Ingestion

6. `PUT /loadSources` (multipart form-data, one or many files) → `200 [document_id, ...]`
   Per file, CCBE expects headers:

   * `userIds`: comma-separated user IDs (tenancy/collections)
   * `title`: logical document title
   * `modified`: ISO date/time string (source system mtime)
   * `provider`: source system label (e.g., “nextcloud”)
   * `content-length`: integer byte size (used to detect changes)

   Flow (unchanged externally):

   * Parse `userIds` → list → `ensure_collections()` → `collection_ids` (list of UUIDs).
   * Find existing doc by `title`; compare `modified` and `content-length` to decide noop vs delete+recreate.
   * Upsert using a temp file (preserve extension).
   * Return the created/updated document IDs.

### 6.3 Query

7. `POST /query` → `200 { answer, context, ... }`
   **Body (unchanged)** includes (names from upstream):

   * `userId` (string) — active user/tenancy context
   * `query` (string) — the question
   * `ctxLimit` (int, optional) — retrieval depth/chunk count
   * `scopeType` (optional) — e.g., “collections”, “documents”, etc.
   * `scopeList` (optional) — list of IDs for the chosen scope

   Flow:

   * Adapter `.search()` returns ranked text+metadata.
   * CCBE assembles the prompt and generates answer as upstream does.

> If your tree includes any other route (e.g., document/admin utilities), it must remain unchanged and be wired to the adapter where it touches storage. The **router auto-export** in §9 will ensure we don’t miss any.

---

## 7) Config & Env

```
# Common
APP_VERSION=4.0.2
RAG_BACKEND=builtin           # default; set to r2r|pinecone|supabase to switch

# R2R
R2R_BASE_URL=http://127.0.0.1:7272

# Pinecone (scaffold)
PINECONE_API_KEY=
PINECONE_INDEX=
PINECONE_ENV=

# Supabase (scaffold)
SUPABASE_URL=
SUPABASE_ANON_KEY=
SUPABASE_TABLE=
```

---

## 8) Logging & errors

* Log AppAPI headers at debug for `/enabled`, `/heartbeat`, `/init`, `/loadSources`.
* If `collection_ids` is not a list (e.g., a string), return `400` with a clear message.
* Keep concise client errors; detailed traces in server logs.
* When adapter is selected but not implemented → `501 {"detail": "backend not implemented"}`.

---

## 9) Documentation & “exhaustive list” guarantee

* **Auto-export endpoint doc** at build/test time by introspecting FastAPI’s router:

  * Generate `docs/endpoints.md` from `app.routes` (method, path, params, bodies, response\_model if any).
  * CI fails if the generated file differs from the committed one (forces docs to stay exhaustive and current).
* Keep a human-readable section in `README.md` linking to `docs/endpoints.md`, with request/response examples.

---

## 10) Testing

**Unit**

* Backend selection from env.
* Built-in backend smoke (unchanged behavior).
* R2R:

  * `ensure_collections()` (existing vs new).
  * Upsert policy (noop vs delete+recreate) using `modified` and `content-length`.
  * `collection_ids` type checks.
* `/enabled` param handling via `FQuery`.

**Integration**

* AppAPI flow: `GET /heartbeat` → `PUT /enabled` → `POST /init` (background progress hits 100).
* `/loadSources`: upload 2 files with headers; reupload without changes → noop; change `modified` or `content-length` → re-ingest.
* `/query`: basic retrieval+answer path.

**Regression**

* Version header middleware present on all responses (whatever upstream uses).
* Router auto-export matches docs.

---

## 11) Implementation notes (lessons applied)

* **Init endpoint**: return `{}` immediately; send progress asynchronously via OCS until `100`. If fatal, include `{"error": "..."}`.
* **Enabled param**: avoid `Query` name collisions—`from fastapi import Query as FQuery`.
* **R2R ingestion**: `collection_ids` must be a **list**; never a joined string.
* **Temp files**: keep extension to preserve type inference.
* **Middleware**: add once (e.g., in `main.py`), not in the router module.
* **Headers**: parse `userIds` safely, trim whitespace, ignore empties.

---

## 12) Minimal-diff plan

* Add `backends/` (4 files: `base.py`, `builtin_pgvector.py`, `r2r.py`, plus two small scaffolds).
* In `main.py`:

  * Build adapter from `RAG_BACKEND`, store on `app.state.rag_backend`.
  * (If not already present) add version header middleware once.
* In `controller.py`:

  * Replace direct storage calls with adapter methods at seam points.
  * **Do not** change route decorators, function signatures, or payload models.
* Add a tiny script that dumps the router map to `docs/endpoints.md` during CI.

---

## 13) Timeline

* **Day 1**: Add interface + `BuiltinBackend` wrapper (no behavior change). Wire selection.
* **Day 2**: Implement `R2RBackend` (collections, upsert, search) with lessons above.
* **Day 3**: `/init` background worker + OCS progress, logging.
* **Day 4**: Tests + router auto-doc.
* **Day 5**: E2E with Nextcloud AppAPI; open PR (small diff).

---

## 14) Open questions

* Should we cache `title → document_id` to avoid paging on “find by title” for large corpora? (Configurable, optional.)
* Do we need chunk-level vs doc-level retrieval harmonization across backends? (Hide in adapter; keep route output stable.)
* Rate limiting/backoff for large batch ingests?

---

### Example glue (sketch)

```python
# main.py
import os
from fastapi import FastAPI
from .controller import router
from .backends.builtin_pgvector import BuiltinBackend
from .backends.r2r import R2RBackend

def build_backend(kind: str):
    k = (kind or "builtin").lower()
    if k == "builtin": return BuiltinBackend()  # wraps upstream code paths
    if k == "r2r":     return R2RBackend()
    raise NotImplementedError(f"{k} backend not implemented")

app = FastAPI()
app.state.rag_backend = build_backend(os.getenv("RAG_BACKEND", "builtin"))
app.include_router(router)
```

```python
# controller seam (ingest)
backend = request.app.state.rag_backend
user_ids = [u.strip() for u in src.headers["userIds"].split(",") if u.strip()]
mapping = backend.ensure_collections(user_ids)
collection_ids = list(mapping.values())  # MUST be a list of UUID strings
doc_id = backend.upsert_document(temp_path, metadata, collection_ids)
```

---

**Bottom line:** upstream stays default (no surprises), the adapter seam is tiny and isolated, R2R is a drop-in via env, and every endpoint is documented and test-verified so Nextcloud AppAPI always gets a valid response—no matter which backend is selected.
