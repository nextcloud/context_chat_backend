#
# SPDX-FileCopyrightText: 2023 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#

# isort: off
from .chain.types import ContextException, LLMOutput, ScopeType, SearchResult
from .types import LoaderException, EmbeddingException
from .vectordb.types import DbException, SafeDbException, UpdateAccessOp
# isort: on
# ruff: noqa: I001

import json
import logging
import multiprocessing as mp
import os
import tempfile
import threading
import time
import zipfile
from collections.abc import Callable, Mapping
from contextlib import asynccontextmanager
from functools import wraps
from pathlib import Path
from threading import Event, Thread
from time import sleep
from typing import Annotated, Any, cast

import requests
from fastapi import BackgroundTasks, Body, FastAPI, Query as FQuery, Request, UploadFile
from langchain.llms.base import LLM
from langchain.schema import Document
from nc_py_api import AsyncNextcloudApp, NextcloudApp
from nc_py_api.ex_app import persistent_storage, set_handlers
from pydantic import BaseModel, ValidationInfo, field_validator
from starlette.responses import FileResponse
from httpx import HTTPStatusError

from .chain.context import do_doc_search, get_context_chunks
from .chain.ingest.injest import embed_sources
from .chain.one_shot import _LLM_TEMPLATE, process_context_query, process_query
from .chain.query_proc import get_pruned_query
from .config_parser import get_config
from .dyn_loader import LLMModelLoader, VectorDBLoader
from .models.types import LlmException
from .ocs_utils import AppAPIAuthMiddleware
from .setup_functions import ensure_config_file, repair_run, setup_env_vars
from .utils import (
    JSONResponse,
    exec_in_proc,
    is_valid_provider_id,
    is_valid_source_id,
    sanitize_source_ids,
    value_of,
)
from .vectordb.service import (
    count_documents_by_provider,
    decl_update_access,
    delete_by_provider,
    delete_by_source,
    delete_user,
    update_access,
)

# setup

setup_env_vars()
repair_run()
ensure_config_file()
logger = logging.getLogger("ccb.controller")
RAG_BACKEND = os.getenv("RAG_BACKEND", "builtin").lower()

models_to_fetch = {}
if RAG_BACKEND == "builtin":
    models_to_fetch = {
        # embedding model
        "https://huggingface.co/Ralriki/multilingual-e5-large-instruct-GGUF/resolve/8738f8d3d8f311808479ecd5756607e24c6ca811/multilingual-e5-large-instruct-q6_k.gguf": {  # noqa: E501
            "save_path": os.path.join(
                persistent_storage(), "model_files", "multilingual-e5-large-instruct-q6_k.gguf"
            )
        },
        # tokenizer model for estimating token count of queries
        "gpt2": {
            "cache_dir": os.path.join(persistent_storage(), "model_files/hub"),
            "allow_patterns": [
                "config.json",
                "merges.txt",
                "tokenizer.json",
                "tokenizer_config.json",
                "vocab.json",
            ],
            "revision": "607a30d783dfa663caf39e06633721c8d4cfcd7e",
        },
    }
app_enabled = Event()


def enabled_handler(enabled: bool, _: NextcloudApp | AsyncNextcloudApp) -> str:
    if enabled:
        app_enabled.set()
    else:
        app_enabled.clear()

    logger.info(f"App {('disabled', 'enabled')[enabled]}")
    return ""


def _get_user_ids(headers: Mapping[str, str]) -> list[str]:
    raw = (
        headers.get("userIds")
        or headers.get("userids")
        or headers.get("userid")
        or headers.get("user-id")
        or headers.get("user_ids")
        or ""
    )
    if raw.startswith("["):
        try:
            data = json.loads(raw)
        except Exception:
            return []
        if isinstance(data, list):
            return [str(u).strip() for u in data if str(u).strip()]
        return []
    return [u.strip() for u in raw.split(",") if u.strip()]


def _write_temp_file(content: bytes, title: str) -> str:
    suffix = Path(title).suffix
    with tempfile.NamedTemporaryFile("wb", delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        return tmp.name


def _safe_remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _report_progress(nextcloud_url: str, app_id: str, secret: str, progress: int, error: str | None = None) -> None:
    url = f"{nextcloud_url}/ocs/v1.php/apps/app_api/ex-app/status"
    headers = {
        "OCS-APIRequest": "true",
        "Accept": "application/json",
        "Authorization-App-Api": secret,
    }
    payload: dict[str, Any] = {"progress": progress}
    if error:
        payload["error"] = error
    try:
        requests.put(url, json=payload, headers=headers, timeout=10)
    except Exception:
        logger.exception("failed to report init progress")


def _init_job(request: Request) -> None:
    nc = os.getenv("NEXTCLOUD_URL", "").rstrip("/")
    secret = os.getenv("APP_SECRET", "12345")
    try:
        if getattr(request.app.state, "rag_backend", None):
            _report_progress(nc, "context_chat_backend", secret, 50)
        time.sleep(0.1)
        _report_progress(nc, "context_chat_backend", secret, 100)
    except Exception as e:
        _report_progress(nc, "context_chat_backend", secret, 100, error=str(e))


@asynccontextmanager
async def lifespan(app: FastAPI):
    set_handlers(app, enabled_handler, models_to_fetch=models_to_fetch)
    nc = NextcloudApp()
    if nc.enabled_state:
        app_enabled.set()
    logger.info(f"App enable state at startup: {app_enabled.is_set()}")
    t = Thread(target=background_thread_task, args=())
    t.start()

    if RAG_BACKEND == "r2r":
        import asyncio
        from .startup_tests import run_startup_tests

        async def _run_tests() -> None:
            await asyncio.sleep(1)
            base = f"http://{os.getenv('APP_HOST', '127.0.0.1')}:{os.getenv('APP_PORT', '9000')}"
            await run_startup_tests(base)

        app.state.startup_test = asyncio.create_task(_run_tests())

    yield
    if vectordb_loader is not None:
        vectordb_loader.offload()
    llm_loader.offload()


app_config = get_config(os.environ["CC_CONFIG_PATH"])
app = FastAPI(debug=app_config.debug, lifespan=lifespan)  # pyright: ignore[reportArgumentType]

app.extra["CONFIG"] = app_config


# loaders

vectordb_loader = VectorDBLoader(app_config) if RAG_BACKEND == "builtin" else None
llm_loader = LLMModelLoader(app, app_config)


# locks and semaphores

# sequential prompt processing for in-house LLMs (non-nc_texttotext)
llm_lock = threading.Lock()

# lock to update the sources dict currently being processed
index_lock = threading.Lock()
_indexing = {}

# limit the number of concurrent document parsing
doc_parse_semaphore = mp.Semaphore(app_config.doc_parser_worker_limit)


# middlewares

if not app_config.disable_aaa:
    app.add_middleware(AppAPIAuthMiddleware)

# logger background thread


def background_thread_task():
    while True:
        logger.info(f"Currently indexing {len(_indexing)} documents (filename, size): ", extra={"_indexing": _indexing})
        sleep(10)


# exception handlers


@app.exception_handler(DbException)
async def _(request: Request, exc: DbException):
    logger.exception(f"Db Error: {request.url.path}:", exc_info=exc)
    return JSONResponse(f"Vector DB Error: {exc}", 500)


@app.exception_handler(SafeDbException)
async def _(request: Request, exc: SafeDbException):
    logger.exception(f"Safe Db Error: {request.url.path}:", exc_info=exc)
    if len(exc.args) > 1:
        return JSONResponse(exc.args[0], exc.args[1])
    return JSONResponse(str(exc), 400)


@app.exception_handler(LoaderException)
async def _(request: Request, exc: LoaderException):
    logger.exception(f"Loader Error: {request.url.path}:", exc_info=exc)
    return JSONResponse(f"Resource Loader Error: {exc}", 500)


@app.exception_handler(ContextException)
async def _(request: Request, exc: ContextException):
    logger.exception(f"Context Retrieval Error: {request.url.path}:", exc_info=exc)
    return JSONResponse(f"Context Retrieval Error: {exc}", 400)


@app.exception_handler(ValueError)
async def _(request: Request, exc: ValueError):
    logger.exception(f"Error: {request.url.path}:", exc_info=exc)
    return JSONResponse(f"Error: {exc}", 400)


@app.exception_handler(LlmException)
async def _(request: Request, exc: LlmException):
    logger.exception(f"Llm Error: {request.url.path}:", exc_info=exc)
    return JSONResponse(f"LLM Error: {exc}", 500)


@app.exception_handler(EmbeddingException)
async def _(request: Request, exc: EmbeddingException):
    logger.exception(f"Error occurred in an embedding request: {request.url.path}:", exc_info=exc)
    return JSONResponse(f"Embedding Request Error: {exc}", 500)


# guards


def enabled_guard(app: FastAPI):
    def decorator(func: Callable):
        """
        Decorator to check if the service is enabled
        """

        @wraps(func)
        def wrapper(*args, **kwargs):
            disable_aaa = app.extra["CONFIG"].disable_aaa
            if not disable_aaa and not app_enabled.is_set():
                return JSONResponse("Context Chat is disabled, enable it from AppAPI to use it.", 503)

            return func(*args, **kwargs)

        return wrapper

    return decorator


# routes


@app.get("/")
def _(request: Request):
    """
    Server check
    """
    return f"Hello, {request.scope.get('username', 'anon')}!"


@app.put("/enabled")
def _(enabled: int = FQuery(default=1, description="Enable=1 or Disable=0")):
    enabled_handler(bool(enabled), None)  # type: ignore[arg-type]
    return JSONResponse("", 200)


@app.get("/enabled")
def _():
    return JSONResponse(content={"enabled": app_enabled.is_set()}, status_code=200)


@app.post("/init")
def _(background: BackgroundTasks, request: Request):
    background.add_task(_init_job, request)
    return JSONResponse({})


@app.post("/updateAccessDeclarative")
@enabled_guard(app)
def _(
    request: Request,
    userIds: Annotated[list[str], Body()],
    sourceId: Annotated[str, Body()],
):
    logger.debug(
        "Update access declarative request:",
        extra={
            "user_ids": userIds,
            "source_id": sourceId,
        },
    )

    if len(userIds) == 0:
        return JSONResponse("Empty list of user ids", 400)

    backend = getattr(request.app.state, "rag_backend", None)
    if backend:
        # Delegate to the external RAG backend when available
        try:
            backend.decl_update_access(userIds, sourceId)
        except NotImplementedError:
            return JSONResponse("Operation not supported", 501)
        return JSONResponse("Access updated")

    if not is_valid_source_id(sourceId):
        return JSONResponse("Invalid source id", 400)

    exec_in_proc(target=decl_update_access, args=(vectordb_loader, userIds, sourceId))

    return JSONResponse("Access updated")


@app.post("/updateAccess")
@enabled_guard(app)
def _(
    request: Request,
    op: Annotated[UpdateAccessOp, Body()],
    userIds: Annotated[list[str], Body()],
    sourceId: Annotated[str, Body()],
):
    """Allow or deny users access to a document."""

    logger.debug(
        "Update access request",
        extra={
            "op": op,
            "user_ids": userIds,
            "source_id": sourceId,
        },
    )

    if not userIds:
        return JSONResponse("Empty list of user ids", 400)

    backend = getattr(request.app.state, "rag_backend", None)
    if backend is not None:

        # Delegate to the external RAG backend when available
        try:
            backend.update_access(op, userIds, sourceId)
        except NotImplementedError:
            return JSONResponse("Operation not supported", 501)
        return JSONResponse("Access updated")

    if not is_valid_source_id(sourceId):
        return JSONResponse("Invalid source id", 400)

    exec_in_proc(
        target=update_access,
        args=(vectordb_loader, op, userIds, sourceId),
    )

    return JSONResponse("Access updated")


@app.post("/updateAccessProvider")
@enabled_guard(app)
def _(
    request: Request,
    op: Annotated[UpdateAccessOp, Body()],
    userIds: Annotated[list[str], Body()],
    providerId: Annotated[str, Body()],
):
    logger.debug(
        "Update access by provider request",
        extra={
            "op": op,
            "user_ids": userIds,
            "provider_id": providerId,
        },
    )

    if len(userIds) == 0:
        return JSONResponse("Empty list of user ids", 400)

    if getattr(request.app.state, "rag_backend", None):
        return JSONResponse("Operation not supported", 501)

    if not is_valid_provider_id(providerId):
        return JSONResponse("Invalid provider id", 400)

    exec_in_proc(target=update_access, args=(vectordb_loader, op, userIds, providerId))

    return JSONResponse("Access updated")


@app.post("/deleteSources")
@enabled_guard(app)
def _(request: Request, sourceIds: Annotated[list[str], Body(embed=True)]):
    logger.debug(
        "Delete sources request",
        extra={
            "source_ids": sourceIds,
        },
    )
    sourceIds = sanitize_source_ids(sourceIds)
    if len(sourceIds) == 0:
        return JSONResponse("No valid sources provided", 400)

    backend = getattr(request.app.state, "rag_backend", None)
    if backend:
        failed: list[str] = []
        for sid in sourceIds:
            try:
                backend.delete_document(sid)
            except HTTPStatusError as exc:  # pragma: no cover - log and continue
                logger.warning(
                    "Failed to delete source via backend",
                    extra={"source_id": sid, "error": str(exc)},
                )
                failed.append(sid)
        if failed:
            return JSONResponse({"message": "Some sources could not be deleted", "failed": failed}, 400)
        return JSONResponse("All valid sources deleted")

    res = exec_in_proc(target=delete_by_source, args=(vectordb_loader, sourceIds))
    if res is False:
        return JSONResponse("Error: VectorDB delete failed, check vectordb logs for more info.", 400)

    return JSONResponse("All valid sources deleted")


@app.post("/deleteProvider")
@enabled_guard(app)
def _(request: Request, providerKey: str = Body(embed=True)):
    logger.debug("Delete sources by provider for all users request", extra={"provider_key": providerKey})

    if value_of(providerKey) is None:
        return JSONResponse("Invalid provider key provided", 400)

    if getattr(request.app.state, "rag_backend", None):
        return JSONResponse("Operation not supported", 501)

    exec_in_proc(target=delete_by_provider, args=(vectordb_loader, providerKey))

    return JSONResponse("All valid sources deleted")


@app.post("/deleteUser")
@enabled_guard(app)
def _(request: Request, userId: str = Body(embed=True)):
    logger.debug("Remove access list for user, and orphaned sources", extra={"user_id": userId})

    if value_of(userId) is None:
        return JSONResponse("Invalid userId provided", 400)

    if getattr(request.app.state, "rag_backend", None):
        return JSONResponse("Operation not supported", 501)

    exec_in_proc(target=delete_user, args=(vectordb_loader, userId))

    return JSONResponse("User deleted")


@app.post("/countIndexedDocuments")
@enabled_guard(app)
def _(request: Request):
    backend = getattr(request.app.state, "rag_backend", None)
    if backend:
        count = len(backend.list_documents())
        return JSONResponse({"all": count})

    counts = exec_in_proc(target=count_documents_by_provider, args=(vectordb_loader,))
    return JSONResponse(counts)


@app.put("/loadSources")
@enabled_guard(app)
def _(request: Request, sources: list[UploadFile]):
    global _indexing

    if len(sources) == 0:
        return JSONResponse("No sources provided", 400)

    backend = getattr(request.app.state, "rag_backend", None)
    if backend:
        loaded_ids: list[str] = []
        for source in sources:
            user_ids = _get_user_ids(source.headers)
            title = source.headers.get("title", source.filename)
            modified = source.headers.get("modified")
            provider = source.headers.get("provider")
            raw_filename = source.filename or ""
            sanitized = sanitize_source_ids([raw_filename])
            if not sanitized:
                logger.error(
                    "Invalid source filename",
                    extra={"source_id": source.filename, "title": title},
                )
                return JSONResponse(
                    f"Invalid source filename for: {source.filename}", 400
                )
            filename = sanitized[0]

            if not (user_ids and title and modified and modified.isdigit() and provider):
                logger.error(
                    "Invalid/missing headers received",
                    extra={
                        "source_id": filename,
                        "title": title,
                        "headers": source.headers,
                    },
                )
                return JSONResponse(f"Invaild/missing headers for: {filename}", 400)

            mapping = backend.ensure_collections(user_ids)
            collection_ids = list(mapping.values())
            logger.debug(
                "ensured collections",
                extra={"user_ids": user_ids, "collection_ids": collection_ids},
            )

            content_bytes = source.file.read()
            size = len(content_bytes)
            source.file.close()
            tmp_path = _write_temp_file(content_bytes, title)
            metadata = {
                "title": title,
                "provider": provider,
                "modified": modified,
                "content-length": size,
                "filename": filename,
                "source": filename,
                "type": source.headers.get("type", ""),
            }
            doc_id = backend.upsert_document(tmp_path, metadata, collection_ids)
            _safe_remove(tmp_path)
            loaded_ids.append(doc_id)

        return JSONResponse({"loaded_sources": loaded_ids, "sources_to_retry": []})

    # builtin path
    for source in sources:
        if not value_of(source.filename):
            return JSONResponse(f"Invalid source filename for: {source.headers.get('title')}", 400)

        with index_lock:
            if source.filename in _indexing:
                # this request will be retried by the client
                return JSONResponse(
                    f"This source ({source.filename}) is already being processed in another request, try again later",
                    503,
                    headers={"cc-retry": "true"},
                )

        if not (
            value_of(source.headers.get("userIds"))
            and value_of(source.headers.get("title"))
            and value_of(source.headers.get("type"))
            and value_of(source.headers.get("modified"))
            and source.headers["modified"].isdigit()
            and value_of(source.headers.get("provider"))
        ):
            logger.error(
                "Invalid/missing headers received",
                extra={
                    "source_id": source.filename,
                    "title": source.headers.get("title"),
                    "headers": source.headers,
                },
            )
            return JSONResponse(f"Invaild/missing headers for: {source.filename}", 400)

    # wait for 10 minutes before failing the request
    semres = doc_parse_semaphore.acquire(block=True, timeout=10 * 60)
    if not semres:
        return JSONResponse(
            "Document parser worker limit reached, try again in some time or consider increasing the limit",
            503,
            headers={"cc-retry": "true"},
        )

    with index_lock:
        for source in sources:
            _indexing[source.filename] = source.size

    try:
        loaded_sources, not_added_sources = exec_in_proc(
            target=embed_sources, args=(vectordb_loader, app.extra["CONFIG"], sources)
        )
    except (DbException, EmbeddingException):
        raise
    except Exception as e:
        raise DbException("Error: failed to load sources") from e
    finally:
        with index_lock:
            for source in sources:
                _indexing.pop(source.filename, None)
        doc_parse_semaphore.release()

    if len(loaded_sources) != len(sources):
        logger.debug(
            "Some sources were not loaded",
            extra={
                "Count of loaded sources": f"{len(loaded_sources)}/{len(sources)}",
                "source_ids": loaded_sources,
            },
        )

    # loaded sources include the existing sources that may only have their access updated
    return JSONResponse({"loaded_sources": loaded_sources, "sources_to_retry": not_added_sources})


class Query(BaseModel):
    userId: str
    query: str
    useContext: bool = True
    scopeType: ScopeType | None = None
    scopeList: list[str] | None = None
    ctxLimit: int = 20

    @field_validator("userId", "query", "ctxLimit")
    @classmethod
    def check_empty_values(cls, value: Any, info: ValidationInfo):
        if value_of(value) is None:
            raise ValueError("Empty value for field", info.field_name)

        return value

    @field_validator("ctxLimit")
    @classmethod
    def at_least_one_context(cls, value: int):
        if value < 1:
            raise ValueError("Invalid context chunk limit")

        return value


def execute_query(query: Query, in_proc: bool = True) -> LLMOutput:
    llm: LLM = llm_loader.load()
    template = app.extra.get("LLM_TEMPLATE")
    no_ctx_template = app.extra["LLM_NO_CTX_TEMPLATE"]
    # todo: array
    end_separator = app.extra.get("LLM_END_SEPARATOR", "")

    if query.useContext:
        target = process_context_query
        args = (
            query.userId,
            vectordb_loader,
            llm,
            app_config,
            query.query,
            query.ctxLimit,
            query.scopeType,
            query.scopeList,
            template,
            end_separator,
        )
    else:
        target = process_query
        args = (
            query.userId,
            llm,
            app_config,
            query.query,
            no_ctx_template,
            end_separator,
        )

    if in_proc:
        return exec_in_proc(target=target, args=args)

    return target(*args)  # pyright: ignore


@app.post("/query")
@enabled_guard(app)
def _(query: Query, request: Request) -> LLMOutput:
    logger.debug("received query request", extra={"query": query.dict()})

    backend = getattr(request.app.state, "rag_backend", None)
    if backend and query.useContext:
        llm: LLM = llm_loader.load()
        template = app.extra.get("LLM_TEMPLATE")
        end_separator = app.extra.get("LLM_END_SEPARATOR", "")
        hits = backend.search(
            user_id=query.userId,
            query=query.query,
            ctx_limit=query.ctxLimit,
            scope_type=query.scopeType,
            scope_list=query.scopeList,
        )
        docs = [Document(page_content=h.get("page_content", ""), metadata=h.get("metadata", {})) for h in hits]
        if len(docs) == 0:
            raise ContextException("No documents retrieved, please index a few documents first")
        context_chunks = get_context_chunks(docs)
        logger.debug("context retrieved", extra={"len(context_chunks)": len(context_chunks)})
        stop = [end_separator] if end_separator else None
        output = llm.invoke(
            get_pruned_query(llm, app_config, query.query, template or _LLM_TEMPLATE, context_chunks),
            stop=stop,
            userid=query.userId,
        ).strip()

        unique_sources: list[str] = list(
            {cast(str, d.metadata["source"]) for d in docs if d.metadata.get("source")}
        )
        return LLMOutput(output=output, sources=unique_sources)

    if app_config.llm[0] == "nc_texttotext":
        return execute_query(query)

    with llm_lock:
        return execute_query(query, in_proc=False)


@app.post("/docSearch")
@enabled_guard(app)
def _(query: Query, request: Request) -> list[SearchResult]:
    backend = getattr(request.app.state, "rag_backend", None)
    if backend:
        hits = backend.search(
            user_id=query.userId,
            query=query.query,
            ctx_limit=query.ctxLimit,
            scope_type=query.scopeType,
            scope_list=query.scopeList,
        )
        return [
            {
                "source_id": h.get("metadata", {}).get("source", ""),
                "title": h.get("metadata", {}).get("title", ""),
            }
            for h in hits
        ]

    # useContext from Query is not used here
    return exec_in_proc(
        target=do_doc_search,
        args=(
            query.userId,
            query.query,
            vectordb_loader,
            query.ctxLimit,
            query.scopeType,
            query.scopeList,
        ),
    )


@app.get("/downloadLogs")
def download_logs() -> FileResponse:
    with tempfile.NamedTemporaryFile("wb", delete=False) as tmp:
        with zipfile.ZipFile(tmp, mode="w", compression=zipfile.ZIP_DEFLATED) as zip_file:
            files = os.listdir(os.path.join(persistent_storage(), "logs"))
            for file in files:
                file_path = os.path.join(persistent_storage(), "logs", file)
                if os.path.isfile(file_path):  # Might be a folder (just skip it then)
                    zip_file.write(file_path)
        return FileResponse(tmp.name, media_type="application/zip", filename="docker_logs.zip")
