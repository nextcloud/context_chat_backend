
# Nextcloud Assistant Context Chat Backend

[![REUSE status](https://api.reuse.software/badge/github.com/nextcloud/context_chat_backend)](https://api.reuse.software/info/github.com/nextcloud/context_chat_backend)

This fork introduces a **pluggable Retrieval-Augmented Generation (RAG) backend** architecture with **zero-change upstream behavior by default**.

* **Default (no config needed):** the **current built-in backend** used by upstream CCBE.
* **Opt-in:** swap to an external backend—e.g., **R2R Graph RAG**, Pinecone, Supabase—via `.env` only. The RAG store can live in its own container or a managed service.

The diff to upstream is intentionally small (adapter layer + light wiring). See **[PRD.md](PRD.md)** for the full spec, including endpoint guarantees and the plugin interface.

> \[!NOTE]
> Install the backend **before** the Context Chat PHP app. Context Chat will background-index user-accessible files; failed attempts to an uninitialized backend are retried on the next job run.
>
> The HTTP request timeout is 50 minutes by default and can be changed with `occ config:app:set context_chat request_timeout --value=3000` (seconds). If you use Docker socket proxy, align that too. See: [Slow responding ExApps](https://github.com/cloud-py-api/docker-socket-proxy?tab=readme-ov-file#slow-responding-exapps)
>
> An end-to-end CUDA example is at the end of this README.
>
> Admin docs: [https://docs.nextcloud.com/server/latest/admin\_manual/ai/app\_context\_chat.html](https://docs.nextcloud.com/server/latest/admin_manual/ai/app_context_chat.html)

---

## Choose your RAG backend (via `.env`)

By default, this fork behaves exactly like upstream (built-in backend). To opt-in to another backend, set:

```bash
# Default: upstream behavior (no changes to your setup)
RAG_BACKEND=builtin

# Optional: R2R Graph RAG
# RAG_BACKEND=r2r
# R2R_BASE_URL=http://127.0.0.1:7272
# R2R_API_KEY=your_api_key_here  # sent as X-API-Key
# R2R_API_TOKEN=your_token_here  # optional bearer token

# Optional: Pinecone (scaffold)
# RAG_BACKEND=pinecone
# PINECONE_API_KEY=
# PINECONE_INDEX=
# PINECONE_ENV=

# Optional: Supabase (scaffold)
# RAG_BACKEND=supabase
# SUPABASE_URL=
# SUPABASE_ANON_KEY=
# SUPABASE_TABLE=
```

* **`builtin` (default):** exact upstream behavior; no code path changes.
* **`r2r`:** uses an external **R2R** server. Make sure `R2R_BASE_URL` is reachable from CCBE. If authentication is required,
  set `R2R_API_KEY` (sent as `X-API-Key`) and/or `R2R_API_TOKEN` (bearer token).
* **`pinecone` / `supabase`:** scaffolds included; selecting them returns HTTP `501` until implemented.

> Endpoint paths, request/response shapes, and status codes remain identical for all backends.

---

## R2R quick start (optional)

1. Run or reach an R2R server (e.g., `http://127.0.0.1:7272`).
2. Set:

   ```bash
   RAG_BACKEND=r2r
   R2R_BASE_URL=http://127.0.0.1:7272
   # R2R_API_KEY=your_api_key_here  # sent as X-API-Key
   # R2R_API_TOKEN=your_token_here
   ```
3. Start CCBE. On `/init`, the backend verifies connectivity.
4. Upload sources (Nextcloud will do this automatically via the Context Chat app).

   * The `loadSources` endpoint expects a `userIds` header as a **comma-separated list**.
   * Collections are created per user and linked automatically.
5. Query as usual. CCBE’s query endpoint and answer shape are unchanged.

**Integration lessons baked in**

* `/init` returns `{}` immediately and reports progress (1–100) asynchronously via OCS.
* The `PUT /enabled?enabled=0|1` param is parsed with `fastapi.Query` (no Pydantic name clash).
* For ingestion, **`collection_ids` must be a list of UUID strings** (not a comma-joined string).
* The `userIds` header is parsed as comma-separated → list → mapped to per-user collections.

---

## Simple Install

Install these **in order**:

* [AppAPI (Apps page)](https://apps.nextcloud.com/apps/app_api)
* [Context Chat Backend (External Apps page)](https://apps.nextcloud.com/apps/context_chat_backend) — **use the same major/minor version as the Context Chat app**
* [Context Chat (Apps page)](https://apps.nextcloud.com/apps/context_chat) — **same major/minor as the backend**
* [Assistant (Apps page)](https://apps.nextcloud.com/apps/assistant) — recommended universal UI / OCP Task Processing consumer
* A Text2Text provider like [llm2 (External Apps)](https://apps.nextcloud.com/apps/llm2) or [integration\_openai (Apps)](https://apps.nextcloud.com/apps/integration_openai)

> \[!NOTE]
> See [AppAPI’s deploy daemon config](#configure-the-appapis-deploy-daemon).
>
> For GPU: enable GPU in AppAPI’s Deploy Daemon (Admin settings → AppAPI).

> \[!IMPORTANT]
> To avoid task execution delay, configure **4 background job workers** on the main server:
> [https://docs.nextcloud.com/server/latest/admin\_manual/ai/overview.html#improve-ai-task-pickup-speed](https://docs.nextcloud.com/server/latest/admin_manual/ai/overview.html#improve-ai-task-pickup-speed)

---

## Complex Install (without docker)

0. Install everything from [Simple Install](#simple-install) **except** Context Chat Backend; set up background workers.
1. `python -m venv .venv`
2. `. .venv/bin/activate`
3. `pip install --upgrade pip setuptools wheel`
4. `pip install -r requirements.txt`
5. Copy `example.env` → `.env` and set variables (see **Choose your RAG backend** above).
6. Ensure `persistent_storage/config.yaml` points to the right config (cpu vs gpu). If unsure, delete it—on launch, it’s recreated (defaults to GPU).
7. Edit `persistent_storage/config.yaml` for model/config needs.
8. Set up PostgreSQL externally or use `dockerfile_scripts/pgsql/install.sh` (Debian-family).
9. Set `EXTERNAL_DB` or the `pgvector.connection` in config to your Postgres connection string if using external DB.
10. Start the DB (see `dockerfile_scripts/pgsql/setup.sh`).
11. `./main.py`
12. [Register as an Ex-App](#register-as-an-ex-app)

> Using `RAG_BACKEND=r2r`? Your external R2R handles retrieval/storage; some local `vectordb`/embedding config entries may not apply.

---

## Complex Install (with docker)

0. Install from [Simple Install](#simple-install) **except** Context Chat Backend; set up background workers.
1. Build the image

   ```bash
   # Good moment to edit example.env (add RAG_BACKEND and provider vars)
   docker build -t context_chat_backend . -f Dockerfile
   ```
2. Run

   ```bash
   docker run -p 10034:10034 \
     --env-file example.env \
     context_chat_backend
   ```

   * If Nextcloud runs locally: add `--add-host=host.docker.internal:host-gateway` and align `NEXTCLOUD_URL`.
3. (Optional) Mount persistence

   ```bash
   -v $(pwd)/persistent_storage:/app/persistent_storage
   ```

   Ensure `persistent_storage/config.yaml` points to the correct config (or delete it to autogenerate).
4. [Configure AppAPI’s deploy daemon](#configure-the-appapis-deploy-daemon)
5. [Register as an Ex-App](#register-as-an-ex-app)

---

## Register as an Ex-App

**1) Create a manual deploy daemon**

```bash
occ app_api:daemon:register --net host manual_install "Manual Install" manual-install http <host> <nextcloud_url>
```

* `host` is `localhost` if Nextcloud can reach it directly; or `host.docker.internal` if Nextcloud runs in Docker and the backend is on the host.
* If Nextcloud is containerized, add `--add-host` to the Nextcloud container (see docker example above).

**2) Register the app (adapt version/port)**

```bash
occ app_api:app:register context_chat_backend manual_install --json-info \
"{\"appid\":\"context_chat_backend\",\"name\":\"Context Chat Backend\",\"daemon_config_name\":\"manual_install\",\"version\":\"4.4.1\",\"secret\":\"12345\",\"port\":10034,\"scopes\":[],\"system_app\":0}" \
--force-scopes --wait-finish
```

Unregister:

```bash
occ app_api:app:unregister context_chat_backend --force
```

---

## Configure the AppAPI’s deploy daemon

Ensure Docker is installed and the default deploy daemon works (Admin settings → AppAPI).

**Recommended:** Docker socket proxy
[https://github.com/cloud-py-api/docker-socket-proxy](https://github.com/cloud-py-api/docker-socket-proxy)

Alternative: grant the web server user access to `/var/run/docker.sock`.

* Compose:

  ```yaml
  volumes:
    - /var/run/docker.sock:/var/run/docker.sock:ro
  ```
* Docker:

  ```bash
  -v /var/run/docker.sock:/var/run/docker.sock:ro
  ```

---

## Logs

Logs live under `logs/` inside the persistent directory. In Docker: `/nc_app_context_chat_backend/logs/`.

* Main log: `ccb.log`, JSONL, rotates at **20 MB** with **10 backups**.
* Console prints warnings and above; set `debug: true` in config to get verbose logs in the file.
* Embedding server logs: `logs/embedding_server_[date].log` (raw stdout/stderr, rotates daily).

---

## Configuration

The effective config is `$APP_PERSISTENT_STORAGE/config.yaml`
(default: `/nc_app_context_chat_backend_data/config.yaml` in the container).

* Top-level options are editable. In sections `vectordb`, `embedding`, and `llm`, only the **first** listed key is used.
* See the example configs for common loader/adapter options; check LangChain docs for others (e.g., LlamaCpp options: [https://api.python.langchain.com/en/latest/llms/langchain\_community.llms.llamacpp.LlamaCpp.html](https://api.python.langchain.com/en/latest/llms/langchain_community.llms.llamacpp.LlamaCpp.html)).

Restart the app after changes (e.g., `docker restart nc_app_context_chat_backend`).

> If `RAG_BACKEND=r2r`, the external R2R server owns the vector store; local `vectordb` settings may be ignored.

---

## Repair

v2.1.0 adds repair steps (run at startup).

`repair2001_date20240412153300.py` removes the existing `config.yaml` so hardware detection can choose an appropriate default (CPU/GPU).
To skip a repair step, add its filename to `repair.info`:

```bash
echo repair2001_date20240412153300.py > "$APP_PERSISTENT_STORAGE/repair.info"
```

Generate a repair file (bump **MINOR** at least):

```bash
APP_VERSION="2.1.0" ./genrepair.sh
```

---

## End-to-End Example: Build & Register (CUDA)

**1) Build**

```bash
cd /your/path/to/the/cloned/repository
docker build --no-cache -f Dockerfile -t context_chat_backend_dev:latest .
```

**2) Run**

```text
Hint: adjust example.env (RAG_BACKEND, etc.) to your environment.
```

```bash
docker run \
  -v ./config.yaml:/app/config.yaml \
  -v ./context_chat_backend:/app/context_chat_backend \
  -v /var/run/docker.sock:/var/run/docker.sock \
  --env-file example.env \
  -p 10034:10034 \
  -e CUDA_VISIBLE_DEVICES=0 \
  -v persistent_storage:/app/persistent_storage \
  --gpus=all \
  context_chat_backend_dev:latest
```

**3) Register**

```text
Hint: ensure the container from step 2 is running on the specified port.
```

```bash
cd /var/www/<your_nextcloud_instance_webroot>
sudo -u www-data php occ app_api:app:unregister context_chat_backend
sudo -u www-data php occ app_api:app:register \
  context_chat_backend \
  manual_install \
  --json-info "{\"appid\":\"context_chat_backend\",\
                \"name\":\"Context Chat Backend\",\
                \"daemon_config_name\":\"manual_install\",\
                \"version\":\"4.4.1\",\
                \"secret\":\"12345\",\
                \"port\":10034,\
                \"scopes\":[],\
                \"system_app\":0}" \
  --force-scopes \
  --wait-finish
```

Successful output should include:

```
ExApp context_chat_backend successfully unregistered.
ExApp context_chat_backend deployed successfully.
ExApp context_chat_backend successfully registered.
```

Container logs will show enable/init:

```
App enabled
INFO: ... "PUT /enabled?enabled=1 HTTP/1.1" 200 OK
INFO: ... "POST /init HTTP/1.1" 200 OK
```

---

## Troubleshooting & integration notes

* **AppAPI init:** `/init` should return `{}` immediately; progress is reported asynchronously (1–100) via OCS `PUT /ocs/v1.php/apps/app_api/ex-app/status`. Include `"error"` if initialization fails fatally.
* **Enabled toggle:** use `PUT /enabled?enabled=0|1`. Internally we use `fastapi.Query` (aliased) to avoid Pydantic’s `Query` name collision.
* **Source ingestion:** the `userIds` file header must be a **comma-separated list** (e.g., `abc, def`).
  For external backends like R2R, **`collection_ids` are sent as a list of UUID strings**—never as a single comma-joined string.
* **Logs:** set `debug: true` in config to capture detailed traces in `ccb.log`.

---

## Endpoint compatibility

All CCBE endpoints keep their **paths, methods, parameters, and payloads unchanged**, regardless of backend.
This repo generates an exhaustive router map in CI to ensure parity. See **`docs/endpoints.md`** for the full, up-to-date list and examples.

---
