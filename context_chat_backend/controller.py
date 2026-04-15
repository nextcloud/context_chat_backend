#
# SPDX-FileCopyrightText: 2023 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
from nc_py_api.ex_app.providers.task_processing import TaskProcessingProvider

# isort: off
from .chain.types import ContextException
from .types import LoaderException, EmbeddingException
from .vectordb.types import DbException, SafeDbException
from .setup_functions import ensure_config_file, repair_run, setup_env_vars

# setup env vars before importing other modules
setup_env_vars()

# ruff: noqa: E402

import logging
import multiprocessing as mp
import os
import tempfile
import threading
import zipfile
from collections.abc import Callable
from contextlib import asynccontextmanager
from functools import wraps

from fastapi import FastAPI, Request
from nc_py_api import AsyncNextcloudApp, NextcloudApp
from nc_py_api.ex_app import persistent_storage, set_handlers
from starlette.responses import FileResponse

from .config_parser import get_config
from .dyn_loader import VectorDBLoader
from .models.types import LlmException
from nc_py_api.ex_app import AppAPIAuthMiddleware
from .utils import JSONResponse, exec_in_proc
from .task_fetcher import THREAD_STOP_EVENT, start_bg_threads, trigger_handler, wait_for_bg_threads
from .vectordb.service import count_documents_by_provider

# setup

# only run once
if mp.current_process().name == 'MainProcess':
	repair_run()
	ensure_config_file()

logger = logging.getLogger('ccb.controller')
app_config = get_config(os.environ['CC_CONFIG_PATH'])
__download_models_from_hf = os.environ.get('CC_DOWNLOAD_MODELS_FROM_HF', 'true').lower() in ('1', 'true', 'yes')

models_to_fetch = {
	# embedding model
	'https://huggingface.co/Ralriki/multilingual-e5-large-instruct-GGUF/resolve/8738f8d3d8f311808479ecd5756607e24c6ca811/multilingual-e5-large-instruct-q6_k.gguf': {  # noqa: E501
		'save_path': os.path.join(persistent_storage(), 'model_files',  'multilingual-e5-large-instruct-q6_k.gguf')
	},
	# tokenizer model for estimating token count of queries
	'gpt2': {
		'cache_dir': os.path.join(persistent_storage(), 'model_files/hub'),
		'allow_patterns': ['config.json', 'merges.txt', 'tokenizer.json', 'tokenizer_config.json', 'vocab.json'],
		'revision': '607a30d783dfa663caf39e06633721c8d4cfcd7e',
	}
} if __download_models_from_hf else {}
app_enabled = threading.Event()

def enabled_handler(enabled: bool, nc: NextcloudApp | AsyncNextcloudApp) -> str:
	try:
		if enabled:
			provider = TaskProcessingProvider(
				id='context_chat-context_chat_search',
				name='Context Chat',
				task_type='context_chat:context_chat_search',
				expected_runtime=30,
				input_shape_defaults={
					'limit': 10,
				},
			)
			nc.providers.task_processing.register(provider)
			provider = TaskProcessingProvider(
				id='context_chat-context_chat',
				name='Context Chat',
				task_type='context_chat:context_chat',
				expected_runtime=30,
			)
			nc.providers.task_processing.register(provider)
			app_enabled.set()
			if THREAD_STOP_EVENT.is_set():
				# If the threads were previously stopped, we start them again
				# otherwise the lifecycle handler has already started them
				start_bg_threads(app_config)
				THREAD_STOP_EVENT.clear()
		else:
			app_enabled.clear()
			wait_for_bg_threads()
	except Exception as e:
		logger.exception('Error in enabled handler:', exc_info=e)
		return f'Error in enabled handler: {e}'

	logger.info(f'App {("disabled", "enabled")[enabled]}')
	return ''


@asynccontextmanager
async def lifespan(app: FastAPI):
	set_handlers(app, enabled_handler, models_to_fetch=models_to_fetch, trigger_handler=trigger_handler)
	start_bg_threads(app_config)
	nc = NextcloudApp()
	logger.info(f'App enable state at startup: {nc.enabled_state}')
	yield
	vectordb_loader.offload()
	wait_for_bg_threads()


app = FastAPI(debug=app_config.debug, lifespan=lifespan)  # pyright: ignore[reportArgumentType]

app.extra['CONFIG'] = app_config


# loaders

vectordb_loader = VectorDBLoader(app_config)


# locks and semaphores

# sequential prompt processing for in-house LLMs (non-nc_texttotext)
llm_lock = threading.Lock()

# lock to update the sources dict currently being processed
index_lock = threading.Lock()
_indexing = {}


# middlewares

if not app_config.disable_aaa:
	app.add_middleware(AppAPIAuthMiddleware)

# exception handlers

@app.exception_handler(DbException)
async def _(request: Request, exc: DbException):
	logger.exception(f'Db Error: {request.url.path}:', exc_info=exc)
	return JSONResponse(f'Vector DB Error: {exc}', 500)


@app.exception_handler(SafeDbException)
async def _(request: Request, exc: SafeDbException):
	logger.exception(f'Safe Db Error: {request.url.path}:', exc_info=exc)
	if len(exc.args) > 1:
		return JSONResponse(exc.args[0], exc.args[1])
	return JSONResponse(str(exc), 400)


@app.exception_handler(LoaderException)
async def _(request: Request, exc: LoaderException):
	logger.exception(f'Loader Error: {request.url.path}:', exc_info=exc)
	return JSONResponse(f'Resource Loader Error: {exc}', 500)


@app.exception_handler(ContextException)
async def _(request: Request, exc: ContextException):
	logger.exception(f'Context Retrieval Error: {request.url.path}:', exc_info=exc)
	return JSONResponse(f'Context Retrieval Error: {exc}', 400)


@app.exception_handler(ValueError)
async def _(request: Request, exc: ValueError):
	logger.exception(f'Error: {request.url.path}:', exc_info=exc)
	return JSONResponse(f'Error: {exc}', 400)


@app.exception_handler(LlmException)
async def _(request: Request, exc: LlmException):
	logger.exception(f'Llm Error: {request.url.path}:', exc_info=exc)
	return JSONResponse(f'LLM Error: {exc}', 500)


@app.exception_handler(EmbeddingException)
async def _(request: Request, exc: EmbeddingException):
	logger.exception(f'Error occurred in an embedding request: {request.url.path}:', exc_info=exc)
	return JSONResponse(f'Embedding Request Error: {exc}', 500)


# guards

def enabled_guard(app: FastAPI):
	def decorator(func: Callable):
		'''
		Decorator to check if the service is enabled
		'''
		@wraps(func)
		def wrapper(*args, **kwargs):
			disable_aaa = app.extra['CONFIG'].disable_aaa
			if not disable_aaa and not app_enabled.is_set():
				return JSONResponse('Context Chat is disabled, enable it from AppAPI to use it.', 503)

			return func(*args, **kwargs)

		return wrapper

	return decorator

# routes

@app.get('/')
def _(request: Request):
	'''
	Server check
	'''
	return f'Hello, {request.scope.get("username", "anon")}!'


@app.get('/enabled')
def _():
	return JSONResponse(content={'enabled': app_enabled.is_set()}, status_code=200)


@app.post('/countIndexedDocuments')
@enabled_guard(app)
def _():
	counts = exec_in_proc(target=count_documents_by_provider, args=(vectordb_loader,))
	return JSONResponse(counts)


@app.get('/downloadLogs')
def download_logs() -> FileResponse:
	with tempfile.NamedTemporaryFile('wb', delete=False) as tmp:
		with zipfile.ZipFile(tmp, mode='w', compression=zipfile.ZIP_DEFLATED) as zip_file:
			files = os.listdir(os.path.join(persistent_storage(), 'logs'))
			for file in files:
				file_path = os.path.join(persistent_storage(), 'logs', file)
				if os.path.isfile(file_path): # Might be a folder (just skip it then)
					zip_file.write(file_path)
		return FileResponse(tmp.name, media_type='application/zip', filename='docker_logs.zip')
