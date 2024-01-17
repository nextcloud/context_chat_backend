import os

from dotenv import load_dotenv
import uvicorn

from .controller import app
from .download import model_init
from .models import models
from .utils import to_int
from .vectordb import vector_dbs

load_dotenv()

__all__ = ['create_server', 'vector_dbs', 'models']


def _setup_env_vars():
	'''
	Sets up the environment variables for persistent storage.
	'''
	persistent_storage = os.getenv('APP_PERSISTENT_STORAGE', 'persistent_storage')
	os.environ['APP_PERSISTENT_STORAGE'] = persistent_storage

	vector_db_dir = os.path.join(persistent_storage, 'vector_db_data')
	if not os.path.exists(vector_db_dir):
		os.makedirs(vector_db_dir, 0o750, True)

	model_dir = os.path.join(persistent_storage, 'model_files')
	if not os.path.exists(model_dir):
		os.makedirs(model_dir, 0o750, True)

	os.environ['VECTORDB_DIR'] = os.getenv('VECTORDB_DIR', vector_db_dir)
	os.environ['MODEL_DIR'] = model_dir
	os.environ['SENTENCE_TRANSFORMERS_HOME'] = os.getenv('SENTENCE_TRANSFORMERS_HOME', model_dir)
	os.environ['TRANSFORMERS_CACHE'] = os.getenv('TRANSFORMERS_CACHE', model_dir)


def create_server(config: dict[str, tuple[str, dict]]):
	'''
	Creates a FastAPI server with the given config.

	Args
	----
	config: dict
		A dictionary containing the services to be deployed.
	'''
	_setup_env_vars()

	app.extra['CONFIG'] = config
	app.extra['ENABLED'] = model_init(app)
	print('App', 'enabled' if app.extra['ENABLED'] else 'disabled', 'at startup')

	uvicorn.run(
		app=app,
		host=os.getenv('APP_HOST', '0.0.0.0'),
		port=to_int(os.getenv('APP_PORT'), 9000),
		http='h11',
		interface='asgi3',
		log_level=('warning', 'debug')[os.getenv('DEBUG', '0') == '1'],
		use_colors=True,
		limit_concurrency=100,
		backlog=100,
		timeout_keep_alive=10,
		h11_max_incomplete_event_size=5 * 1024 * 1024,  # 5MB
	)
