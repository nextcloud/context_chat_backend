#
# SPDX-FileCopyrightText: 2023 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
from .chain.types import ContextException, LLMOutput, ScopeType # isort:skip
from .vectordb.types import DbException, SafeDbException, UpdateAccessOp # isort:skip
from .types import LoaderException, EmbeddingException # isort:skip

import logging
import multiprocessing as mp
import os
import threading
from collections.abc import Callable
from contextlib import asynccontextmanager
from functools import wraps
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
from .utils import JSONResponse, exec_in_proc, is_valid_provider_id, is_valid_source_id, value_of
from .vectordb.service import decl_update_access, delete_by_provider, delete_by_source, delete_user, update_access

# setup

setup_env_vars()
repair_run()
ensure_config_file()
logger = logging.getLogger('ccb.controller')

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

	logger.info(f'App {("disabled", "enabled")[enabled]}')
	return ''


@asynccontextmanager
async def lifespan(app: FastAPI):
	set_handlers(app, enabled_handler, models_to_fetch=models_to_fetch)
	nc = NextcloudApp()
	if nc.enabled_state:
		app_enabled.set()
	logger.info(f'App enable state at startup: {app_enabled.is_set()}')
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

# lock to update the sources dict currently being processed
index_lock = threading.Lock()
_indexing = {}

# limit the number of concurrent document parsing
doc_parse_semaphore = mp.Semaphore(app_config.doc_parser_worker_limit)


# middlewares

if not app_config.disable_aaa:
	app.add_middleware(AppAPIAuthMiddleware)


# exception handlers

@app.exception_handler(DbException)
async def _(request: Request, exc: DbException):
	logger.exception(f'Db Error: {request.url.path}:', exc_info=exc)
	return JSONResponse('Vector DB is facing some issues, please check the logs for more info', 500)


@app.exception_handler(SafeDbException)
async def _(request: Request, exc: SafeDbException):
	logger.exception(f'Safe Db Error (user facing): {request.url.path}:', exc_info=exc)
	if len(exc.args) > 1:
		return JSONResponse(exc.args[0], exc.args[1])
	return JSONResponse(str(exc), 400)


@app.exception_handler(LoaderException)
async def _(request: Request, exc: LoaderException):
	logger.exception(f'Loader Error: {request.url.path}:', exc_info=exc)
	return JSONResponse('The resource loader is facing some issues, please check the logs for more info', 500)


@app.exception_handler(ContextException)
async def _(request: Request, exc: ContextException):
	logger.exception(f'Context Retrieval Error: {request.url.path}:', exc_info=exc)
	# error message is safe
	return JSONResponse(str(exc), 400)


@app.exception_handler(ValueError)
async def _(request: Request, exc: ValueError):
	logger.exception(f'Error: {request.url.path}:', exc_info=exc)
	# error message is safe
	return JSONResponse(str(exc), 500)


@app.exception_handler(LlmException)
async def _(request: Request, exc: LlmException):
	logger.exception(f'Llm Error: {request.url.path}:', exc_info=exc)
	# error message should be safe
	return JSONResponse(str(exc), 500)


@app.exception_handler(EmbeddingException)
async def _(request: Request, exc: EmbeddingException):
	logger.exception(f'Error occurred in an embedding request: {request.url.path}:', exc_info=exc)
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
	logger.debug('Update access declarative request:', extra={
		'user_ids': userIds,
		'source_id': sourceId,
	})

	if len(userIds) == 0:
		return JSONResponse('Empty list of user ids', 400)

	if not is_valid_source_id(sourceId):
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
	logger.debug('Update access request', extra={
		'op': op,
		'user_ids': userIds,
		'source_id': sourceId,
	})

	if len(userIds) == 0:
		return JSONResponse('Empty list of user ids', 400)

	if not is_valid_source_id(sourceId):
		return JSONResponse('Invalid source id', 400)

	exec_in_proc(target=update_access, args=(vectordb_loader, op, userIds, sourceId))

	return JSONResponse('Access updated')


@app.post('/updateAccessProvider')
@enabled_guard(app)
def _(
	op: Annotated[UpdateAccessOp, Body()],
	userIds: Annotated[list[str], Body()],
	providerId: Annotated[str, Body()],
):
	logger.debug('Update access by provider request', extra={
		'op': op,
		'user_ids': userIds,
		'provider_id': providerId,
	})

	if len(userIds) == 0:
		return JSONResponse('Empty list of user ids', 400)

	if not is_valid_provider_id(providerId):
		return JSONResponse('Invalid provider id', 400)

	exec_in_proc(target=update_access, args=(vectordb_loader, op, userIds, providerId))

	return JSONResponse('Access updated')


@app.post('/deleteSources')
@enabled_guard(app)
def _(sourceIds: Annotated[list[str], Body(embed=True)]):
	logger.debug('Delete sources request', extra={
		'source_ids': sourceIds,
	})

	sourceIds = [source.strip() for source in sourceIds if source.strip() != '']

	if len(sourceIds) == 0:
		return JSONResponse('No sources provided', 400)

	res = exec_in_proc(target=delete_by_source, args=(vectordb_loader, sourceIds))
	if res is False:
		return JSONResponse('Error: VectorDB delete failed, check vectordb logs for more info.', 400)

	return JSONResponse('All valid sources deleted')


@app.post('/deleteProvider')
@enabled_guard(app)
def _(providerKey: str = Body(embed=True)):
	logger.debug('Delete sources by provider for all users request', extra={ 'provider_key': providerKey })

	if value_of(providerKey) is None:
		return JSONResponse('Invalid provider key provided', 400)

	exec_in_proc(target=delete_by_provider, args=(vectordb_loader, providerKey))

	return JSONResponse('All valid sources deleted')


@app.post('/deleteUser')
@enabled_guard(app)
def _(userId: str = Body(embed=True)):
	logger.debug('Remove access list for user, and orphaned sources', extra={ 'user_id': userId })

	if value_of(userId) is None:
		return JSONResponse('Invalid userId provided', 400)

	exec_in_proc(target=delete_user, args=(vectordb_loader, userId))

	return JSONResponse('User deleted')


@app.put('/loadSources')
@enabled_guard(app)
def _(sources: list[UploadFile]):
	global _indexing

	if len(sources) == 0:
		return JSONResponse('No sources provided', 400)

	for source in sources:
		if not value_of(source.filename):
			return JSONResponse(f'Invalid source filename for: {source.headers.get("title")}', 400)

		with index_lock:
			if source.filename in _indexing:
				# this request will be retried by the client
				return JSONResponse(
					f'This source ({source.filename}) is already being processed in another request, try again later',
					503,
					headers={'cc-retry': 'true'},
				)

		if not (
			value_of(source.headers.get('userIds'))
			and value_of(source.headers.get('title'))
			and value_of(source.headers.get('type'))
			and value_of(source.headers.get('modified'))
			and source.headers['modified'].isdigit()
			and value_of(source.headers.get('provider'))
		):
			logger.error('Invalid/missing headers received', extra={
				'source_id': source.filename,
				'title': source.headers.get('title'),
				'headers': source.headers,
			})
			return JSONResponse(f'Invaild/missing headers for: {source.filename}', 400)

	# wait for 10 minutes before failing the request
	semres = doc_parse_semaphore.acquire(block=True, timeout=10*60)
	if not semres:
		return JSONResponse(
			'Document parser worker limit reached, try again in some time or consider increasing the limit',
			503,
			headers={'cc-retry': 'true'}
		)

	with index_lock:
		for source in sources:
			_indexing[source.filename] = True

	try:
		added_sources = exec_in_proc(target=embed_sources, args=(vectordb_loader, app.extra['CONFIG'], sources))
	except Exception as e:
		raise DbException('Error: failed to load sources') from e
	finally:
		with index_lock:
			for source in sources:
				_indexing.pop(source.filename, None)
		doc_parse_semaphore.release()

	if len(added_sources) != len(sources):
		logger.debug('Some sources were not loaded', extra={
			'Count of newly loaded sources': f'{len(added_sources)}/{len(sources)}',
			'source_ids': added_sources,
		})

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
	logger.debug('received query request', extra={ 'query': query.dict() })

	if app_config.llm[0] == 'nc_texttotext':
		return execute_query(query)

	with llm_lock:
		return execute_query(query, in_proc=False)
