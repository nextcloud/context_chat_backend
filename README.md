
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

