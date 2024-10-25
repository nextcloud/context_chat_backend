import multiprocessing as mp
import os
import threading
from contextlib import asynccontextmanager
from functools import wraps
from logging import error as log_error
from threading import Event
from typing import Annotated, Any, Callable

from fastapi import BackgroundTasks, Body, FastAPI, Request, UploadFile
from langchain.llms.base import LLM
from nc_py_api import NextcloudApp
from nc_py_api.ex_app import persistent_storage
from nc_py_api.ex_app.integration_fastapi import fetch_models_task
from pydantic import BaseModel, ValidationInfo, field_validator

from .chain import ContextException, LLMOutput, ScopeType, embed_sources, process_context_query, process_query
from .config_parser import get_config
from .dyn_loader import EmbeddingModelLoader, LLMModelLoader, LoaderException, VectorDBLoader
from .models import LlmException
from .ocs_utils import AppAPIAuthMiddleware
from .setup_functions import ensure_config_file, repair_run, setup_env_vars
from .utils import JSONResponse, update_progress, value_of
from .vectordb import BaseVectorDB, DbException

# setup

setup_env_vars()
repair_run()
ensure_config_file()

models_to_fetch = {
	"https://huggingface.co/Ralriki/multilingual-e5-large-instruct-GGUF/resolve/main/multilingual-e5-large-instruct-q6_k.gguf": {
		"save_path": os.path.join(persistent_storage(), 'model_files',  "multilingual-e5-large-instruct-q6_k.gguf")
	}
}
app_enabled = Event()

# disabled for now
# scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
	nc = NextcloudApp()
	if nc.enabled_state:
		app_enabled.set()
	print('\n\nApp', 'enabled' if app_enabled.is_set() else 'disabled', 'at startup', flush=True)
	yield
	vectordb_loader.offload()
	embedding_loader.offload()
	llm_loader.offload()


app_config = get_config(os.environ['CC_CONFIG_PATH'])
app = FastAPI(debug=app_config['debug'], lifespan=lifespan)  # pyright: ignore[reportArgumentType]

app.extra['CONFIG'] = app_config


# loaders

vectordb_loader = VectorDBLoader(app, app_config)
embedding_loader = EmbeddingModelLoader(app, app_config)
llm_loader = LLMModelLoader(app, app_config)


# locks

# sequential prompt processing for in-house LLMs (non-nc_texttotext)
llm_lock = threading.Lock()

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


@app.exception_handler(ContextException)
async def _(request: Request, exc: ContextException):
	log_error(f'Context Retrieval Error: {request.url.path}:', exc)
	# error message is safe
	return JSONResponse(str(exc), 400)


@app.exception_handler(ValueError)
async def _(request: Request, exc: ValueError):
	log_error(f'Error: {request.url.path}:', exc)
	# error message is safe
	return JSONResponse(str(exc), 400)


@app.exception_handler(LlmException)
async def _(request: Request, exc: LlmException):
	log_error(f'Llm Error: {request.url.path}:', exc)
	# error message should be safe
	return JSONResponse(str(exc), 400)

# guards

def enabled_guard(app: FastAPI):
	def decorator(func: Callable):
		'''
		Decorator to check if the service is enabled
		'''
		@wraps(func)
		def wrapper(*args, **kwargs):
			disable_aaa = app.extra['CONFIG']['disable_aaa']
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
	return JSONResponse(content={'enabled': app_enabled.is_set()}, status_code=200)

@app.put('/enabled')
def _(enabled: bool):

	if enabled:
		app_enabled.set()
	else:
		app_enabled.clear()

	print('App', 'enabled' if enabled else 'disabled', flush=True)
	return JSONResponse(content={'error': ''}, status_code=200)


@app.get('/heartbeat')
def _():
	print('heartbeat_handler: result=ok')
	return JSONResponse(content={'status': 'ok'}, status_code=200)


@app.post('/init')
def _(bg_tasks: BackgroundTasks):
	nc = NextcloudApp()
	fetch_models_task(nc, models_to_fetch, 0)
	update_progress(app, 100)
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
		and value_of(source.headers.get('title'))
		and value_of(source.headers.get('type'))
		and value_of(source.headers.get('modified'))
		and value_of(source.headers.get('provider'))
		for source in sources
	):
		return JSONResponse('Invaild/missing headers', 400)

	db: BaseVectorDB = vectordb_loader.load()
	queue = mp.Queue()
	p = mp.Process(target=embed_sources, args=(db, app.extra['CONFIG'], sources, queue))
	p.start()
	p.join()

	result = queue.get()
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
	llm: LLM = llm_loader.load()
	template = app.extra.get('LLM_TEMPLATE')
	no_ctx_template = app.extra['LLM_NO_CTX_TEMPLATE']
	# todo: array
	end_separator = app.extra.get('LLM_END_SEPARATOR', '')

	queue = mp.Queue()

	if query.useContext:
		db: BaseVectorDB = vectordb_loader.load()
		p = mp.Process(
			target=process_context_query,
			args=(
				queue,
				query.userId,
				db,
				llm,
				app_config,
				query.query,
				query.ctxLimit,
				template,
				end_separator,
				query.scopeType,
				query.scopeList,
			),
		)
	else:
		p = mp.Process(
			target=process_query,
			args=(
				queue,
				llm,
				app_config,
				query.query,
				no_ctx_template,
				end_separator,
			),
		)

	p.start()
	p.join()

	return queue.get()


@app.post('/query')
@enabled_guard(app)
def _(query: Query) -> LLMOutput:
	print('query:', query, flush=True)

	if app_config['llm'][0] == 'nc_texttotext':
		return execute_query(query)

	with llm_lock:
		return execute_query(query)
