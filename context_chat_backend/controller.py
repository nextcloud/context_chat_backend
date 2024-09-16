import os
import threading
from contextlib import asynccontextmanager
from logging import error as log_error
from typing import Annotated, Any

from fastapi import BackgroundTasks, Body, FastAPI, Request, UploadFile
from langchain.llms.base import LLM
from pydantic import BaseModel, ValidationInfo, field_validator

from .chain import LLMOutput, QueryProcException, ScopeType, embed_sources, process_context_query, process_query
from .config_parser import get_config
from .download import background_init, ensure_models
from .dyn_loader import EmbeddingModelLoader, LLMModelLoader, LoaderException, VectorDBLoader
from .models import LlmException
from .ocs_utils import AppAPIAuthMiddleware
from .setup_functions import ensure_config_file, repair_run, setup_env_vars
from .utils import JSONResponse, enabled_guard, update_progress, value_of
from .vectordb import BaseVectorDB, DbException

# setup

setup_env_vars()
repair_run()
ensure_config_file()

# disabled for now
# scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(_: FastAPI):
	try:
		# scheduler.start()
		yield
		# scheduler.shutdown()
	finally:
		vectordb_loader.offload()
		embedding_loader.offload()
		llm_loader.offload()


app_config = get_config(os.environ['CC_CONFIG_PATH'])
app = FastAPI(debug=app_config['debug'], lifespan=lifespan)  # pyright: ignore[reportArgumentType]

app.extra['CONFIG'] = app_config
app.extra['ENABLED'] = ensure_models(app)


# loaders

vectordb_loader = VectorDBLoader(app, app_config)
embedding_loader = EmbeddingModelLoader(app, app_config)
llm_loader = LLMModelLoader(app, app_config)


# locks (temporary solution for sequential prompt processing before NC 30)
llm_lock = threading.Lock()


# schedules

# @scheduler.scheduled_job('interval', minutes=app_config['model_offload_timeout'], seconds=1)
# def _():
# 	if app.extra.get('EM_LAST_ACCESSED') is not None \
# 		and (time() - app.extra['EM_LAST_ACCESSED'] > app_config['model_offload_timeout']) * 60:
# 		print('Offloading the embedding model', flush=True)
# 		embedding_loader.offload()
# 		del app.extra['EM_LAST_ACCESSED']

# 	if app.extra.get('LLM_LAST_ACCESSED') is not None \
# 		and (time() - app.extra['LLM_LAST_ACCESSED'] > app_config['model_offload_timeout'] * 60):
# 		print('Offloading the LLM model', flush=True)
# 		llm_loader.offload()
# 		del app.extra['LLM_LAST_ACCESSED']


# middlewares

if not app_config['disable_aaa']:
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


@app.exception_handler(QueryProcException)
async def _(request: Request, exc: QueryProcException):
	log_error(f'QueryProc Error: {request.url.path}:', exc)
	return JSONResponse(str(exc), 400)


@app.exception_handler(ValueError)
async def _(request: Request, exc: ValueError):
	log_error(f'Error: {request.url.path}:', exc)
	return JSONResponse(str(exc), 400)


@app.exception_handler(LlmException)
async def _(request: Request, exc: LlmException):
	log_error(f'Llm Error: {request.url.path}:', exc)
	return JSONResponse(str(exc), 400)

# routes

@app.get('/')
def _(request: Request):
	'''
	Server check
	'''
	return f'Hello, {request.scope.get("username", "anon")}!'


# TODO: for testing, remove later
@app.get('/world')
@enabled_guard(app)
def _(query: str | None = None):
	from langchain.schema.embeddings import Embeddings
	em: Embeddings = embedding_loader.load()
	return em.embed_query(query if query is not None else 'what is an apple?')


# TODO: for testing, remove later
@app.get('/vectors')
@enabled_guard(app)
def _():
	from chromadb.api import ClientAPI

	from .vectordb import get_collection_name

	db: BaseVectorDB = vectordb_loader.load()
	client: ClientAPI | None = db.client

	if client is None:
		return JSONResponse('Error: VectorDB client not initialised', 500)

	vectors = {}
	for user_id in db.get_users():
		db.setup_schema(user_id)
		vectors[user_id] = client.get_collection(get_collection_name(user_id)).get()

	return JSONResponse(vectors)


# TODO: for testing, remove later
@app.get('/search')
@enabled_guard(app)
def _(userId: str, sourceNames: str):
	sourceList = [source.strip() for source in sourceNames.split(',') if source.strip() != '']

	if len(sourceList) == 0:
		return JSONResponse('No sources provided', 400)

	db: BaseVectorDB = vectordb_loader.load()
	source_objs = db.get_objects_from_metadata(userId, 'source', sourceList)
	sources = [s['id'] for s in source_objs.values() if s.get('id') is not None]

	return JSONResponse({ 'sources': sources })


@app.get('/enabled')
def _():
	return JSONResponse(content={'enabled': app.extra.get('ENABLED', False)}, status_code=200)


@app.put('/enabled')
def _(enabled: bool):
	app.extra['ENABLED'] = enabled

	if not enabled:
		vectordb_loader.offload()
		embedding_loader.offload()
		llm_loader.offload()

	print('App', 'enabled' if enabled else 'disabled', flush=True)
	return JSONResponse(content={'error': ''}, status_code=200)


@app.get('/heartbeat')
def _():
	print('heartbeat_handler: result=ok')
	return JSONResponse(content={'status': 'ok'}, status_code=200)


@app.post('/init')
def _(bg_tasks: BackgroundTasks):
	if not app.extra.get('ENABLED', False):
		bg_tasks.add_task(background_init, app)
		return JSONResponse(content={}, status_code=200)

	update_progress(app, 100)
	print('App already initialised', flush=True)
	return JSONResponse(content={}, status_code=200)


@app.post('/deleteSources')
@enabled_guard(app)
def _(userId: Annotated[str, Body()], sourceNames: Annotated[list[str], Body()]):
	print('Delete sources request:', userId, sourceNames)

	sourceNames = [source.strip() for source in sourceNames if source.strip() != '']

	if len(sourceNames) == 0:
		return JSONResponse('No sources provided', 400)

	db: BaseVectorDB = vectordb_loader.load()
	res = db.delete(userId, 'source', sourceNames)

	if res is False:
		return JSONResponse('Error: VectorDB delete failed, check vectordb logs for more info.', 400)

	return JSONResponse('All valid sources deleted')


@app.post('/deleteSourcesByProvider')
@enabled_guard(app)
def _(userId: Annotated[str, Body()], providerKey: Annotated[str, Body()]):
	print('Delete sources by provider request:', userId, providerKey)

	if value_of(providerKey) is None:
		return JSONResponse('Invalid provider key provided', 400)

	db: BaseVectorDB = vectordb_loader.load()
	res = db.delete(userId, 'provider', [providerKey])

	if res is False:
		return JSONResponse('Error: VectorDB delete failed, check vectordb logs for more info.', 400)

	return JSONResponse('All valid sources deleted')


@app.post('/deleteSourcesByProviderForAllUsers')
@enabled_guard(app)
def _(providerKey: str = Body(embed=True)):
	print('Delete sources by provider for all users request:', providerKey)

	if value_of(providerKey) is None:
		return JSONResponse('Invalid provider key provided', 400)

	db: BaseVectorDB = vectordb_loader.load()
	res = db.delete_for_all_users('provider', [providerKey])

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
		and value_of(source.headers.get('type'))
		and value_of(source.headers.get('modified'))
		and value_of(source.headers.get('provider'))
		for source in sources
	):
		return JSONResponse('Invaild/missing headers', 400)

	db: BaseVectorDB = vectordb_loader.load()
	result = embed_sources(db, app.extra['CONFIG'], sources)
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


def execute_query(query: Query) -> LLMOutput:
	# todo: migrate to Depends during db schema change
	llm: LLM = llm_loader.load()

	template = app.extra.get('LLM_TEMPLATE')
	no_ctx_template = app.extra['LLM_NO_CTX_TEMPLATE']
	# todo: array
	end_separator = app.extra.get('LLM_END_SEPARATOR', '')

	if query.useContext:
		db: BaseVectorDB = vectordb_loader.load()
		return process_context_query(
			user_id=query.userId,
			vectordb=db,
			llm=llm,
			app_config=app_config,
			query=query.query,
			ctx_limit=query.ctxLimit,
			template=template,
			end_separator=end_separator,
			scope_type=query.scopeType,
			scope_list=query.scopeList,
		)

	return process_query(
		llm=llm,
		app_config=app_config,
		query=query.query,
		no_ctx_template=no_ctx_template,
		end_separator=end_separator,
	)


@app.post('/query')
@enabled_guard(app)
def _(query: Query) -> LLMOutput:
	global llm_lock
	print('query:', query, flush=True)

	if app_config['llm'][0] == 'nc_texttotext':
		return execute_query(query)

	with llm_lock:
		return execute_query(query)
