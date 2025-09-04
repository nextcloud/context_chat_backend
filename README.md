
# Nextcloud Assistant – Context Chat Backend (CCBE)
**Pluggable retrieval backends with upstream-compatible defaults.**

This fork introduces a thin **adapter layer** that lets administrators choose the retrieval store and RAG/Graph-RAG implementation **without changing** Context Chat’s public API or user experience.

- **Default (no config):** behaves exactly like upstream CCBE (builtin store).
- **Opt-in:** select an external backend (e.g., **R2R Graph RAG**, Pinecone, Supabase) via environment variables only.
- **Same endpoints, same shapes:** request/response contracts and status codes are identical across backends.

---

## Why this exists

RAG and Graph-RAG are evolving quickly. Bundling a single implementation inside CCBE creates operational and strategic constraints for large Nextcloud estates:

- **Operations & risk:** Nextcloud admins can’t independently scale, patch, or migrate very large embedding/graph stores when these are tightly coupled to CCBE.
- **Technology choice:** Sites differ—GPU availability, model policy, preferred vector DB, and graph engines. A fixed in-tree RAG stack can be sub-optimal.
- **Ecosystem reuse:** A decoupled store can serve multiple apps (e.g., OpenWebUI or internal agents) instead of being hardwired to Context Chat.

A **pluggable backend** restores admin control and vendor neutrality while keeping CCBE stable for end-users.

---

## What changes (and what does **not**)

- ✅ **No change for default users**: leave `RAG_BACKEND=builtin` (or unset) and CCBE behaves like upstream.
- ✅ **Backends are swapped by config**: set a single env var and point to your retrieval service.
- ✅ **API compatibility**: endpoint paths, payloads, and status codes are preserved.
- ✅ **Small surface**: the adapter is thin; CCBE remains the “contract owner”.

---

## Architecture at a glance

```

Nextcloud (Context Chat app)  
│ HTTP/OCS (unchanged)  
▼  
Context Chat Backend (CCBE)  
│ Adapter boundary (env-selected)  
▼  
┌──────────────────────────────┬──────────────────────────────┬──────────────────────────────┐  
│ builtin (upstream default) │ R2R Graph RAG (external) │ other providers (scaffold) │  
│ • local vector store │ • collections & graphs │ • pinecone / supabase / ... │  
│ • embeddings in-process │ • dedup (doc→chunk→graph) │ • implement same contract │  
└──────────────────────────────┴──────────────────────────────┴──────────────────────────────┘

````

**Permissions model (R2R example).** CCBE sends a `userIds` header → adapter maps user/group to **collection filters**; queries only traverse collections the caller is allowed to see.

---

## Key benefits (R2R adapter)

- **Aggressive deduplication** from document hash down to chunk/graph nodes → less storage, faster queries.
- **Scale knobs everywhere**: choose embedding models, batch/queue sizes, index sharding, and the **query LLM** independently of CCBE’s release cadence.
- **Graph-RAG** when you need it: relations/entity graphs augment vanilla semantic search for complex corpora.
- **Separation of duties**: CCBE remains a stable Nextcloud component; R2R (or any backend) can scale independently, be upgraded, or be hosted on dedicated hardware.
- **Ecosystem reuse**: the same store can serve OpenWebUI, agents, or offline analytics.

---

## Quick start (default = upstream behavior)

No changes required—install as you do today. CCBE will use the builtin backend.

---

## Opt-in to an external backend (example: R2R)

Set these in your `.env` (or the AppAPI daemon’s env):

```env
# default behavior (no change)
RAG_BACKEND=builtin

# opt-in: R2R Graph RAG
# RAG_BACKEND=r2r
# R2R_BASE_URL=http://127.0.0.1:7272
# R2R_HTTP_TIMEOUT=300           # seconds (optional)
# R2R_API_KEY=...                # sent as X-API-Key (optional)
# R2R_API_TOKEN=...              # Bearer token (optional)
````

**Notes**

- Endpoint contracts are identical across backends.
    
- If using R2R, ensure the backend is reachable from CCBE and collections exist/are auto-provisioned during ingestion.
    

---

## Install

### Simple (typical Nextcloud setup)

1. Install **AppAPI**, **Context Chat Backend (CCBE)**, **Context Chat**, and (optionally) **Assistant** from the Apps pages.
    
2. If you want GPUs, enable GPU support in the AppAPI Deploy Daemon.
    
3. For high throughput, configure multiple background workers on the main server.
    

> CCBE’s adapter is selected purely by env—no code changes to the Nextcloud apps.

### Manual / Docker

- **Manual (venv)**  
    Create a venv, install `requirements.txt`, copy `example.env` → `.env`, set `RAG_BACKEND`, run `./main.py`.
    
- **Docker**  
    Build the image and run with `--env-file` pointing to your `.env`. Mount `persistent_storage` if you want to keep local config/logs across restarts.
    

---

## Register as an Ex-App (manual daemon example)

```bash
# 1) register a manual daemon
occ app_api:daemon:register --net host manual_install "Manual Install" manual-install http <host> <nextcloud_url>

# 2) register CCBE (adapt version/port)
occ app_api:app:register context_chat_backend manual_install --json-info \
'{"appid":"context_chat_backend","name":"Context Chat Backend","daemon_config_name":"manual_install","version":"<x.y.z>","secret":"<secret>","port":10034,"scopes":[],"system_app":0}' \
--force-scopes --wait-finish
```

Unregister with:

```bash
occ app_api:app:unregister context_chat_backend --force
```

---

## Operations

- **Logs** live under `logs/` inside the persistent directory (or the container’s data dir).
    
- **Configuration**: the effective config is `${APP_PERSISTENT_STORAGE}/config.yaml`. Adapter selection happens via env; other sections (e.g., local vectordb/embedding) are ignored when an external backend fully handles retrieval.
    

---

## Security & governance

- **Data plane isolation:** retrieval stores (and GPUs) can be isolated from the web front-end.
    
- **Least privilege:** CCBE holds only the secrets it needs to call the backend; the backend enforces collection scoping.
    
- **Compliance:** independent backup, retention, rotation, and auditing on the backend—without touching CCBE.
    

---

## Roadmap

- **Finalize the “RAG driver” contract** as a short spec (methods, status, `userIds` header, collection semantics).
    
- **Keep builtin as default** for frictionless upgrades; maintainers can merge the adapter hook now without forcing any site to change.
    
- **Out-of-tree providers** (R2R today; Pinecone/Supabase scaffolds provided).
    
- **Contrib tests**: fixtures that hit identical endpoints through each backend and compare shapes/status codes.
    

---

## Credits & Upstream Acknowledgements

This work builds on the excellent engineering by the **Nextcloud Assistant** teams, in particular:
- **Context Chat** (PHP app) – AGPL-3.0. https://github.com/nextcloud/context_chat
- **Context Chat Backend** (External App, Python) – AGPL-3.0+. https://github.com/nextcloud/context_chat_backend

We maintain API compatibility and default behaviour to remain a good citizen in the Nextcloud ecosystem.

## Special thanks

**SciPhi R2R** (https://github.com/SciPhi-AI/R2R) inspired this pluggable backend approach.
R2R demonstrates how a modern retrieval stack—multimodal ingestion, hybrid search,
Graph-RAG, and robust collections/permissions—can be exposed cleanly via a REST API.
Their implementation showed us the value of **decoupling** retrieval from application release cycles
and letting sites select best-fit stores and models operationally.

R2R is MIT-licensed and independently maintained by the SciPhi team; this repository is not
affiliated with or endorsed by SciPhi. We simply thank them for the ideas and excellent engineering.

### Third-Party Notices

This project may interoperate with third-party software and services. Notably:

- **SciPhi R2R** — MIT License. See upstream repository for license terms:
  https://github.com/SciPhi-AI/R2R

All trademarks are the property of their respective owners.

## What would be nice (aspiration)

Adopt a **minimal abstract RAG driver** in Context Chat Backend:

- Keep the **built-in backend as the default** (no changes for existing users).
- Provide a **tiny, stable driver interface** (methods, status, and a small set of request/response shapes).
- Pass **user/group context** (e.g., `userIds`) from CCBE; drivers enforce collection-level filtering.
- Allow **out-of-tree providers** (e.g., R2R, Pinecone, Supabase, Neo4j) to plug in via configuration only.
- Preserve **API compatibility and operational neutrality**—admins can scale/upgrade retrieval independently of CCBE releases.

This keeps Nextcloud vendor-neutral and stable, while enabling teams to use best-fit retrieval stacks. R2R’s clean API surface is a working proof that this pattern is practical today.

---

## Why R2R specifically (rationale and fit)

R2R (SciPhi) exposes a clean, capability‑rich HTTP API for document ingestion, hybrid/semantic search, and optional graph construction. It is a good match for CCBE because:

- Collections as tenancy: R2R models access as per‑tenant/per‑user collections. CCBE can pass `userIds` and the adapter can scope every query to only those collections.
- Document‑centric API: Create/update/delete documents with server‑side hash filtering and metadata updates; avoid client‑side scan/joins.
- Graph‑RAG optionality: Enable entity/relationship graphs where useful, without forcing it for simple deployments.
- Independent scaling: R2R workers, queues, and model endpoints scale outside of CCBE’s lifecycle.

See also: `R2R-Integration.md` for more background and deployment notes.

---

## Collections‑based access model (user → collection) 

CCBE never sends raw user ACLs to the backend at query time. Instead the adapter translates user context to R2R collections and uses these as filters:

- Ensure collections: On every ingestion call, CCBE resolves the `userIds` header and calls `GET /v3/collections`; missing entries are created with `POST /v3/collections { name: <userId> }`.
- Ingest scope: New or existing documents are associated with the set of collection IDs for all `userIds` in the request.
- Query scope: Search/RAG requests include a filter: `filters: { collection_ids: { $overlap: [ userId ] } }` (or the resolved collection IDs), ensuring hits only from the caller’s collections.
- Access updates: Grant/revoke operations add/remove the document from the corresponding user collections.

This keeps the user access layer simple, auditable, and entirely enforced on the retrieval side.

---

## Endpoint mapping (CCBE ⇄ R2R)

High‑level map of how CCBE endpoints translate into R2R calls when `RAG_BACKEND=r2r`:

- `PUT /loadSources` →
  - `GET /v3/collections` (list) → `POST /v3/collections` (create missing)
  - For each source: dedup by hash via `POST /v3/retrieval/search` (query "*" with metadata filter)
  - `GET /v3/documents/{id}` to read authoritative fields when needed
  - Create or update document via `POST /v3/documents` (multipart) and `PUT /v3/documents/{id}/metadata`
  - Add/remove collection membership: `POST/DELETE /v3/collections/{cid}/documents/{id}`

- `POST /updateAccessDeclarative` →
  - `GET /v3/documents/{id}/collections` then reconcile with `POST/DELETE /v3/collections/{cid}/documents/{id}`

- `POST /updateAccess` (allow/deny) →
  - `POST/DELETE /v3/collections/{cid}/documents/{id}`

- `POST /deleteSources` → `DELETE /v3/documents/{id}` (by identifier)

- `POST /countIndexedDocuments` → `GET /v3/documents` (count client‑side)

- `POST /query` and `POST /docSearch` → `POST /v3/retrieval/rag` with collection filter and optional scope

For a detailed walkthrough with file/line references, see `docs/ccbe_r2r_mapping.md` and `R2R-Integration.md`.

---

## Backpressure and timeouts: how we keep scans alive

Large batches and upstream spikes used to surface as 500s/timeouts for the Nextcloud client. We implemented a minimal, upstream‑compatible strategy focused on two goals: avoid timeouts and make every busy condition retryable.

What we do now
- Caller‑side gate in the R2R adapter:
  - Cap concurrent upserts from CCBE (`R2R_MAX_INFLIGHT_UPSERTS`).
  - Optional quick wait (`R2R_MAX_WAIT_SECONDS`) to see if capacity returns.
  - If still busy/timeout/502–504, raise a small `RetryableBackendBusy` with the specific `source_id`.
- Central response shaping in `main.py`:
  - For `/loadSources`, map `RetryableBackendBusy` to HTTP 200 with body:
    `{ "loaded_sources": [], "sources_to_retry": ["<source_id>"] }`
  - For other routes, return HTTP 503 with header `cc-retry: true` and optional `Retry-After`.

Why this works
- The Context Chat client expects either success with `sources_to_retry` or a retryable signal. Returning 200 for `/loadSources` keeps the scanner’s queue alive and moves on to other files; that single source is re‑queued automatically.
- We removed complex queue probing by default; local, caller‑side signals are enough and reduce false positives.

Tuning knobs (env)
- `R2R_MAX_INFLIGHT_UPSERTS` (default 3): cap concurrent creates from CCBE to R2R.
- `R2R_MAX_WAIT_SECONDS` (default 10): small grace period before responding.
- `R2R_RETRY_AFTER_SECONDS` (default 10): included on 503 responses for non‑/loadSources.
- `R2R_HEALTH_MAX_RTT_MS` (default 0 = disabled): EWMA latency‑based gating; can be re‑enabled if desired.
- RabbitMQ mgmt probe is disabled by default; re‑enable via `QUEUE_HEALTH_URL` et al. if your ops need it.

Related guardrails
- Upsert skip windows cache: `R2R_SKIP_UPSERT_ALL_WITHIN_SECS` and `R2R_SKIP_UPSERT_META_WITHIN_SECS` avoid re‑ingesting recently seen content.
- Local exclude list: `R2R_EXCLUDE_EXTS` lets CCBE skip uploads the R2R policy would reject (e.g., `.xls,.xlsx`).

---

## Configuration quick reference (R2R)

Essential
```env
RAG_BACKEND=r2r
R2R_BASE_URL=http://<host>:7272
R2R_API_KEY=...            # optional
R2R_API_TOKEN=...          # optional
R2R_HTTP_TIMEOUT=300       # optional
```

Performance and stability
```env
# Caller-side backpressure (recommended)
R2R_MAX_INFLIGHT_UPSERTS=3
R2R_MAX_WAIT_SECONDS=10
R2R_RETRY_AFTER_SECONDS=10
# Latency gate (off by default)
R2R_HEALTH_MAX_RTT_MS=0
# Skip windows to avoid needless re‑ingest
R2R_SKIP_UPSERT_ALL_WITHIN_SECS=172800
R2R_SKIP_UPSERT_META_WITHIN_SECS=345600
# Optional local file excludes
R2R_EXCLUDE_EXTS=.tsv,.csv,.xls,.xlsx,.bmp,.heic,.jpeg,.jpg,.png,.tiff
```

Optional (ops)
```env
# RabbitMQ mgmt probe (disabled by default)
QUEUE_HEALTH_URL=http://<r2r-host>:15673
QUEUE_HEALTH_USER=user
QUEUE_HEALTH_PASSWORD=password
QUEUE_MAX_MESSAGES=0
QUEUE_MAX_PER_CONSUMER=0
```

---

## Troubleshooting (field notes)

- “At least one source is already being processed…”
  - Early behavior on 503/timeout. Now mitigated: `/loadSources` responds 200 with `sources_to_retry`, so the scanner continues.

- R2R shows “main thread may be blocked” yet RabbitMQ looks idle
  - The backlog was inside the HTTP request path (synchronous work, upstream latency). Caller‑side caps and quick retries are designed to prevent this manifesting as a client timeout.

- After restart, “old” items complete
  - Hatchet stores runs/steps in Postgres and rehydrates queues on restart; documents created at 03:00 can finish at 07:30 and retain their original `created_at`.

- Embeddings timeouts / litellm 500s
  - Expand capacity or route embeddings to a healthy provider. CCBE will mark the file for retry and proceed with the rest of the batch.

---

## Data flow (ingest → search)

1) Client calls `PUT /loadSources` with files + `userIds` headers.
2) Adapter ensures per‑user collections; dedups by document hash; creates/updates documents; associates them with user collections.
3) Optional extraction/graph steps run asynchronously (Hatchet) in R2R.
4) Queries (`/query`, `/docSearch`) call `POST /v3/retrieval/rag` with collection filters and optional scope.
5) Answers are returned with normalized hits; access is enforced by collection membership.

This pattern keeps CCBE’s contract stable and lets R2R evolve independently (models, queues, and graph features) without affecting the Nextcloud integration.
