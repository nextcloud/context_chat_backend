from .chain.types import ContextException, LLMOutput, ScopeType # isort:skip
from .vectordb.types import DbException, UpdateAccessOp # isort:skip
from .types import LoaderException, EmbeddingException # isort:skip

import multiprocessing as mp
import os
import threading
from collections.abc import Callable
from contextlib import asynccontextmanager
from functools import wraps
from logging import error as log_error
from threading import Event
from typing import Annotated, Any

from fastapi import Body, FastAPI, Request, UploadFile
from langchain.llms.base import LLM
from nc_py_api import AsyncNextcloudApp, NextcloudApp
from nc_py_api.ex_app import persistent_storage, set_handlers
from pydantic import BaseModel, ValidationInfo, field_validator

from .chain.ingest.injest import embed_sources
from .chain.one_shot import process_context_query, process_query
from .config_parser import get_config
from .dyn_loader import EmbeddingModelLoader, LLMModelLoader, VectorDBLoader
from .models.types import LlmException
from .ocs_utils import AppAPIAuthMiddleware
from .setup_functions import ensure_config_file, repair_run, setup_env_vars
from .utils import JSONResponse, exec_in_proc, is_valid_source_id, value_of
from .vectordb.service import decl_update_access, delete_by_provider, delete_by_source, update_access

# setup

setup_env_vars()
repair_run()
ensure_config_file()

models_to_fetch = {
	"https://huggingface.co/Ralriki/multilingual-e5-large-instruct-GGUF/resolve/8738f8d3d8f311808479ecd5756607e24c6ca811/multilingual-e5-large-instruct-q6_k.gguf": {  # noqa: E501
		"save_path": os.path.join(persistent_storage(), 'model_files',  "multilingual-e5-large-instruct-q6_k.gguf")
	}
}
app_enabled = Event()

def enabled_handler(enabled: bool, _: NextcloudApp | AsyncNextcloudApp) -> str:
	if enabled:
		app_enabled.set()
	else:
		app_enabled.clear()

	print('App', 'enabled' if enabled else 'disabled', flush=True)
	return ''


@asynccontextmanager
async def lifespan(app: FastAPI):
	set_handlers(app, enabled_handler, models_to_fetch=models_to_fetch)
	nc = NextcloudApp()
	if nc.enabled_state:
		app_enabled.set()
	print('\n\nApp', 'enabled' if app_enabled.is_set() else 'disabled', 'at startup', flush=True)
	yield
	vectordb_loader.offload()
	embedding_loader.offload()
	llm_loader.offload()


app_config = get_config(os.environ['CC_CONFIG_PATH'])
app = FastAPI(debug=app_config.debug, lifespan=lifespan)  # pyright: ignore[reportArgumentType]

app.extra['CONFIG'] = app_config


# loaders

# global embedding_loader so the server is not started multiple times
embedding_loader = EmbeddingModelLoader(app_config)
vectordb_loader = VectorDBLoader(embedding_loader, app_config)
llm_loader = LLMModelLoader(app, app_config)


# locks and semaphores

# sequential prompt processing for in-house LLMs (non-nc_texttotext)
llm_lock = threading.Lock()

# limit the number of concurrent document parsing
doc_parse_semaphore = mp.Semaphore(app_config.doc_parser_worker_limit)


# middlewares

if not app_config.disable_aaa:
	app.add_middleware(AppAPIAuthMiddleware)


# exception handlers

@app.exception_handler(DbException)
async def _(request: Request, exc: DbException):
	log_error(f'Db Error: {request.url.path}:', exc)
	return JSONResponse('Vector DB is facing some issues, please check the logs for more info', 500)


@app.exception_handler(LoaderException)
async def _(request: Request, exc: LoaderException):
	log_error(f'Loader Error: {request.url.path}:', exc)
	return JSONResponse('The resource loader is facing some issues, please check the logs for more info', 500)


@app.exception_handler(ContextException)
async def _(request: Request, exc: ContextException):
	log_error(f'Context Retrieval Error: {request.url.path}:', exc)
	# error message is safe
	return JSONResponse(str(exc), 400)


@app.exception_handler(ValueError)
async def _(request: Request, exc: ValueError):
	log_error(f'Error: {request.url.path}:', exc)
	# error message is safe
	return JSONResponse(str(exc), 500)


@app.exception_handler(LlmException)
async def _(request: Request, exc: LlmException):
	log_error(f'Llm Error: {request.url.path}:', exc)
	# error message should be safe
	return JSONResponse(str(exc), 500)


# todo: exception is thrown in another process
@app.exception_handler(EmbeddingException)
async def _(request: Request, exc: EmbeddingException):
	log_error(f'Error occurred in an embedding request: {request.url.path}:', exc)
	return JSONResponse('Some error occurred in the request to the embedding server, please check the logs for more info', 500)  # noqa: E501


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


@app.post('/updateAccessDeclarative')
@enabled_guard(app)
def _(
	userIds: Annotated[list[str], Body()],
	sourceId: Annotated[str, Body()],
):
	if len(userIds) == 0:
		return JSONResponse('Empty list of user ids', 400)

	if is_valid_source_id(sourceId):
		return JSONResponse('Invalid source id', 400)

	exec_in_proc(target=decl_update_access, args=(vectordb_loader, userIds, sourceId))

	return JSONResponse('Access updated')


@app.post('/updateAccess')
@enabled_guard(app)
def _(
	op: Annotated[UpdateAccessOp, Body()],
	userIds: Annotated[list[str], Body()],
	sourceId: Annotated[str, Body()],
):
	if len(userIds) == 0:
		return JSONResponse('Empty list of user ids', 400)

	if is_valid_source_id(sourceId):
		return JSONResponse('Invalid source id', 400)

	exec_in_proc(target=update_access, args=(vectordb_loader, op, userIds, sourceId))

	return JSONResponse('Access updated')


# todo: update call in php to not include user_ids
@app.post('/deleteSources')
@enabled_guard(app)
def _(sourceNames: Annotated[list[str], Body()]):
	print('Delete sources request:', sourceNames)

	sourceNames = [source.strip() for source in sourceNames if source.strip() != '']

	if len(sourceNames) == 0:
		return JSONResponse('No sources provided', 400)

	res = exec_in_proc(target=delete_by_source, args=(vectordb_loader, sourceNames))
	if res is False:
		return JSONResponse('Error: VectorDB delete failed, check vectordb logs for more info.', 400)

	return JSONResponse('All valid sources deleted')


@app.post('/deleteProvider')
@enabled_guard(app)
def _(providerKey: str = Body(embed=True)):
	print('Delete sources by provider for all users request:', providerKey)

	if value_of(providerKey) is None:
		return JSONResponse('Invalid provider key provided', 400)

	exec_in_proc(target=delete_by_provider, args=(vectordb_loader, providerKey))

	return JSONResponse('All valid sources deleted')


@app.put('/loadSources')
@enabled_guard(app)
def _(sources: list[UploadFile]):
	if len(sources) == 0:
		return JSONResponse('No sources provided', 400)

	for source in sources:
		if not (
			value_of(source.headers.get('userIds'))
			and value_of(source.headers.get('title'))
			and value_of(source.headers.get('type'))
			and value_of(source.headers.get('modified'))
			and source.headers['modified'].isdigit()
			and value_of(source.headers.get('provider'))
		):
			return JSONResponse(f'Invaild/missing headers for: {source.filename}', 400)

		if not value_of(source.filename):
			return JSONResponse(f'Invalid source filename for: {source.headers.get("title")}', 400)

	doc_parse_semaphore.acquire(block=True, timeout=29*60)  # ~29 minutes
	added_sources = exec_in_proc(target=embed_sources, args=(vectordb_loader, app.extra['CONFIG'], sources))
	doc_parse_semaphore.release()

	if len(added_sources) != len(sources):
		print(
			'Count of newly loaded sources:', len(added_sources),
			'/', len(sources),
			'\nSources:', added_sources,
			flush=True,
		)

	return JSONResponse({'loaded_sources': added_sources})


class Query(BaseModel):
	userId: str
	query: str
	useContext: bool = True
	scopeType: ScopeType | None = None
	scopeList: list[str] | None = None
	ctxLimit: int = 20

	@field_validator('userId', 'query', 'ctxLimit')
	@classmethod
	def check_empty_values(cls, value: Any, info: ValidationInfo):
		if value_of(value) is None:
			raise ValueError('Empty value for field', info.field_name)

		return value

	@field_validator('ctxLimit')
	@classmethod
	def at_least_one_context(cls, value: int):
		if value < 1:
			raise ValueError('Invalid context chunk limit')

		return value


def execute_query(query: Query, in_proc: bool = True) -> LLMOutput:
	llm: LLM = llm_loader.load()
	template = app.extra.get('LLM_TEMPLATE')
	no_ctx_template = app.extra['LLM_NO_CTX_TEMPLATE']
	# todo: array
	end_separator = app.extra.get('LLM_END_SEPARATOR', '')

	if query.useContext:
		target = process_context_query
		args=(
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
		target=process_query
		args=(
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


@app.post('/query')
@enabled_guard(app)
def _(query: Query) -> LLMOutput:
	print('query:', query, flush=True)

	if app_config.llm[0] == 'nc_texttotext':
		return execute_query(query)

	with llm_lock:
		return execute_query(query, in_proc=False)
