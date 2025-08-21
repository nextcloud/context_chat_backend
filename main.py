#!/usr/bin/env python3
#
# SPDX-FileCopyrightText: 2023 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
import json
import logging
from importlib import import_module
from os import getenv

import uvicorn

from context_chat_backend.backends.base import RagBackend  # isort: skip
from context_chat_backend.types import TConfig  # isort: skip
from context_chat_backend.controller import app  # isort: skip
from context_chat_backend.utils import to_int  # isort: skip
from context_chat_backend.logger import get_logging_config, setup_logging  # isort: skip

LOGGER_CONFIG_NAME = "logger_config.yaml"


def build_backend() -> RagBackend | None:
    kind = (getenv("RAG_BACKEND") or "builtin").lower()
    if kind in ("", "builtin"):
        return None
    module_name = f"context_chat_backend.backends.{kind}"
    try:
        module = import_module(module_name)
    except ModuleNotFoundError as exc:
        raise ValueError(f"Unknown RAG_BACKEND={kind}") from exc
    class_name = "".join(part.capitalize() for part in kind.split("_")) + "Backend"
    backend_cls = getattr(module, class_name, None)
    if backend_cls is None:
        raise ValueError(f"Backend '{module_name}' does not define {class_name}")
    return backend_cls()


app.state.rag_backend = build_backend()


def _setup_log_levels(debug: bool):
    """
    Set log levels for the modules at once for a cleaner usage later.
    """
    if not debug:
        # warning is the default level
        return

    LOGGERS = (
        "ccb",
        "ccb.chain",
        "ccb.doc_loader",
        "ccb.injest",
        "ccb.models",
        "ccb.vectordb",
        "ccb.controller",
        "ccb.dyn_loader",
        "ccb.ocs_utils",
        "ccb.utils",
    )

    for name in LOGGERS:
        logger = logging.getLogger(name)
        logger.setLevel(logging.DEBUG)


if __name__ == "__main__":
    logging_config = get_logging_config(LOGGER_CONFIG_NAME)
    setup_logging(logging_config)
    app_config: TConfig = app.extra["CONFIG"]
    _setup_log_levels(app_config.debug)
    backend = app.state.rag_backend
    rag_backend_kind = (getenv("RAG_BACKEND") or "builtin").lower()
    backend_config = backend.config() if backend else {}
    config_out = app_config.model_dump()
    config_out["rag_backend"] = [rag_backend_kind, backend_config]
    print("App config:\n" + json.dumps(config_out, indent=2), flush=True)

    uv_log_config = uvicorn.config.LOGGING_CONFIG  # pyright: ignore[reportAttributeAccessIssue]
    uv_log_config["formatters"]["json"] = logging_config["formatters"]["json"]
    uv_log_config["handlers"]["file_json"] = logging_config["handlers"]["file_json"]

    uv_log_config["loggers"]["uvicorn"]["handlers"].append("file_json")
    uv_log_config["loggers"]["uvicorn.access"]["handlers"].append("file_json")

    uvicorn.run(
        app=app,
        host=getenv("APP_HOST", "127.0.0.1"),
        port=to_int(getenv("APP_PORT"), 9000),
        http="h11",
        interface="asgi3",
        log_config=uv_log_config,
        log_level=app_config.uvicorn_log_level,
        use_colors=bool(app_config.use_colors and getenv("CI", "false") == "false"),
        # limit_concurrency=10,
        # backlog=20,
        timeout_keep_alive=120,
        h11_max_incomplete_event_size=5 * 1024 * 1024,  # 5MiB
        workers=app_config.uvicorn_workers,
    )
