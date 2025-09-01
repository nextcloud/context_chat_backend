# Context Chat Backend — R2R Integration Guide

This document captures what we learned integrating the Context Chat Backend (CCBE) with an external R2R retrieval/RAG service and making it work reliably in Nextcloud Context Chat.

## Overview

- CCBE supports two RAG modes controlled by `RAG_BACKEND`:
  - `builtin`: local vector DB + local LLM
  - `r2r`: external R2R service for retrieval and (optionally) generation
- With `r2r`, CCBE calls R2R’s `/v3/retrieval/rag` endpoint to get:
  - `generated_answer`: final LLM answer from R2R
  - `search_results`: chunk hits used to build source references shown in the UI

Key files:

- `context_chat_backend/backends/r2r.py`: R2R HTTP client
- `context_chat_backend/controller.py`: FastAPI app and routes
- `context_chat_backend/chain/query_proc.py`: prompt pruning and token budgeting

## API Usage and Payload Shapes

R2R endpoints used:

- Health/status: `GET /v3/system/status`
- RAG: `POST /v3/retrieval/rag` (primary)
- Search (internal checks): `POST /v3/retrieval/search` (hash/title lookup)

RAG request (minimal):

```json
{
  "query": "...",
  "top_k": 20,
  "filters": {"collection_ids": {"$overlap": ["<userId>"]}}
}
```

RAG response (relevant fields):

```json
{
  "results": {
    "generated_answer": "...",
    "search_results": {
      "chunk_search_results": [
        {
          "text": "...",
          "metadata": {
            "title": "...",
            "source": "files__default:8059480",
            "filename": "files__default:8059480",
            "provider": "files__default",
            "modified": "1718822863",
            "sha256": "..."
          }
        }
      ]
    }
  }
}
```

We tolerate both list and nested forms for hits:

- `results.search_results.chunk_search_results` (preferred)
- Or `results.search_results` as a list

## Controller Flow

Route: `POST /query`

1. When `RAG_BACKEND=r2r` and `useContext=true`, CCBE calls `R2rBackend.rag()` (R2R `/retrieval/rag`).
2. If `generated_answer` exists, CCBE returns it directly to the client.
3. Else it falls back to local LLM prompting: builds a context from hits and invokes the configured local LLM.
4. In both cases, CCBE extracts and returns source references for the UI.

Route: `POST /docSearch`

1. Uses `R2rBackend.search()` (backed by `/retrieval/rag`) to get chunk hits.
2. Emits a list of `{ sourceId, title }` in the format Nextcloud expects.

## Source ID Normalization (Nextcloud expectations)

Nextcloud’s Context Chat expects provider-style identifiers in the UI and linking layer. We normalize R2R metadata into a canonical form:

- Prefer `metadata.source`, then `metadata.filename`, then any `source_id`/`sourceId`.
- Normalize to `"<provider>: <id>"` with a space after `:` (e.g., `files__default: 8059480`).
- If the provider looks like `files_default` (single underscore), convert to double underscore on first segment: `files__default`.
- Deduplicate by `(sourceId, title)` for `/docSearch` and by `sourceId` for `/query` sources.

Implementation references:

- `/query` source building: `context_chat_backend/controller.py`
- `/docSearch` results shaping: `context_chat_backend/controller.py`

## Key Changes and Fixes

1. Use R2R’s generated answer:
   - Added `R2rBackend.rag()` which returns `{ answer, hits }` by calling `/v3/retrieval/rag`.
   - Updated `/query` to prefer `generated_answer` from R2R, falling back to local LLM only if the answer is missing.

2. Token counting fallback:
   - Some local LLMs (e.g., Nextcloud TextToText) don’t implement `get_num_tokens`.
   - `get_pruned_query()` now uses a safe heuristic fallback (~4 chars/token) to avoid crashes before “invoking llm”.

3. FastAPI startup crash (ExceptionMiddleware):
   - Starlette only accepts exception handlers for subclasses of `Exception`.
   - Python 3.11’s `BaseExceptionGroup` derives from `BaseException`, so unconditional registration caused an `AssertionError` at startup.
   - We now conditionally register the handler only when allowed; otherwise we skip it.

## Configuration

Environment variables for R2R:

- `RAG_BACKEND=r2r`
- `R2R_BASE_URL=http://<host>:<port>` (default `http://127.0.0.1:7272`)
- `R2R_API_KEY=<key>` (sends `X-API-Key`)
- `R2R_API_TOKEN=<token>` (sends `Authorization: Bearer …`)
- `R2R_HTTP_TIMEOUT=<seconds>` (default `300`)

Other environment variables commonly used by CCBE:

- `CC_CONFIG_PATH` — path to CCBE config file
- `NEXTCLOUD_URL`, `APP_SECRET` — for AppAPI status reporting
- `APP_HOST`, `APP_PORT` — used by optional startup tests

## Logging and Diagnostics

CCBE logs notable milestones with a request correlation id (`X-Request-ID`):

- `http request` and `http response`
- `R2R request` (as a runnable curl) and `R2R request completed`
- `R2R response body` (for debugging)
- `/query` flow:
  - `received query request`
  - `backend search hits`
  - `context retrieved` (when falling back to local LLM)
  - `invoking llm` and `llm output`
  - `query response` (shows `sources` and truncated `output`)
- `/docSearch` flow:
  - `docSearch hits` (raw hits)
  - `docSearch map` (normalization details)
  - `docSearch results` (final payload to client)

Tip: If the log shows `context retrieved` but not `invoking llm`, the issue is likely in prompt pruning/token counting (now mitigated with the fallback).

## Troubleshooting

- Startup AssertionError in `ExceptionMiddleware`:
  - Caused by registering a handler for `BaseExceptionGroup` (not a subclass of `Exception` in Py3.11).
  - Fixed: conditional registration to avoid the assertion.

- Short LLM answers while on R2R:
  - Cause: CCBE was still invoking the local Nextcloud LLM (which uses conservative defaults) instead of R2R’s generated answer.
  - Fix: Use `R2rBackend.rag()`; prefer R2R `generated_answer` and only fall back to local LLM if it’s missing.

- “No documents retrieved” errors:
  - Ensure documents are indexed and in collections mapped to the querying `userId`.
  - Filters: `filters.collection_ids.$overlap` must include the user’s collection name/ID.

- `context retrieved` but 500 before LLM:
  - Previously due to missing `get_num_tokens`; now handled via heuristic fallback.

## Validation Steps

1. Set `RAG_BACKEND=r2r` and R2R credentials/URL.
2. Start CCBE and confirm health checks pass (`/v3/system/status`).
3. Hit `POST /docSearch` with a known query and `userId`; verify `sourceId` formatting like `files__default: 123`.
4. Hit `POST /query` with the same query:
   - If R2R returns `generated_answer`, it should appear as the final answer in Nextcloud with the same `sources` you see in logs.
   - If not, CCBE will prompt the local LLM (watch for `invoking llm`).

## Notes

- We preserve R2R’s flexibility by tolerating different `results` shapes.
- We avoid leaking secrets in logs by masking `Authorization` and `X-API-Key` in the emitted curl.
- Source normalization specifically targets Context Chat expectations (provider name normalization and a space after `:`).

