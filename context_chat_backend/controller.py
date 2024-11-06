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

from .chain import ContextException, LLMOutput, ScopeType, embed_sources, process_context_query, process_query
from .chain.ingest.delete import delete_by_provider, delete_by_source, delete_for_all_users
from .config_parser import get_config
from .dyn_loader import EmbeddingModelLoader, LLMModelLoader, LoaderException, VectorDBLoader
from .models import LlmException
from .network_em import EmbeddingException
from .ocs_utils import AppAPIAuthMiddleware
from .setup_functions import ensure_config_file, repair_run, setup_env_vars
from .utils import JSONResponse, exec_in_proc, value_of
from .vectordb import DbException

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


@app.post('/deleteSources')
@enabled_guard(app)
def _(userId: Annotated[str, Body()], sourceNames: Annotated[list[str], Body()]):
	print('Delete sources request:', userId, sourceNames)

	sourceNames = [source.strip() for source in sourceNames if source.strip() != '']

	if len(sourceNames) == 0:
		return JSONResponse('No sources provided', 400)

	res = exec_in_proc(target=delete_by_source, args=(vectordb_loader, userId, sourceNames))
	if res is False:
		return JSONResponse('Error: VectorDB delete failed, check vectordb logs for more info.', 400)

	return JSONResponse('All valid sources deleted')


@app.post('/deleteSourcesByProvider')
@enabled_guard(app)
def _(userId: Annotated[str, Body()], providerKey: Annotated[str, Body()]):
	print('Delete sources by provider request:', userId, providerKey)

	if value_of(providerKey) is None:
		return JSONResponse('Invalid provider key provided', 400)

	res = exec_in_proc(target=delete_by_provider, args=(vectordb_loader, userId, providerKey))
	if res is False:
		return JSONResponse('Error: VectorDB delete failed, check vectordb logs for more info.', 400)

	return JSONResponse('All valid sources deleted')


@app.post('/deleteSourcesByProviderForAllUsers')
@enabled_guard(app)
def _(providerKey: str = Body(embed=True)):
	print('Delete sources by provider for all users request:', providerKey)

	if value_of(providerKey) is None:
		return JSONResponse('Invalid provider key provided', 400)

	res = exec_in_proc(target=delete_for_all_users, args=(vectordb_loader, providerKey))
	if res is False:
		return JSONResponse('Error: VectorDB delete failed, check vectordb logs for more info.', 400)

	return JSONResponse('All valid sources deleted')


@app.put('/loadSources')
@enabled_guard(app)
def _(sources: list[UploadFile]):
	if len(sources) == 0:
		return JSONResponse('No sources provided', 400)

	# TODO: headers validation using pydantic
	if not (
		value_of(source.headers.get('userId'))
		and value_of(source.headers.get('title'))
		and value_of(source.headers.get('type'))
		and value_of(source.headers.get('modified'))
		and value_of(source.headers.get('provider'))
		for source in sources
	):
		return JSONResponse('Invaild/missing headers', 400)

	doc_parse_semaphore.acquire(block=True, timeout=29*60)  # ~29 minutes
	result = exec_in_proc(target=embed_sources, args=(vectordb_loader, app.extra['CONFIG'], sources))
	doc_parse_semaphore.release()

	if not result:
		return JSONResponse('Error: All sources were not loaded, check logs for more info', 500)

	return JSONResponse('All sources loaded')


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
			template,
			end_separator,
			query.scopeType,
			query.scopeList,
		)
	else:
		target=process_query
		args=(
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
