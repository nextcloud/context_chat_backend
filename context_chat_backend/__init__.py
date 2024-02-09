import os

from dotenv import load_dotenv

from .config_parser import get_config
from .controller import app
from .download import model_init
from .utils import to_int

load_dotenv()

__all__ = ['app', 'to_int']


def _setup_env_vars():
	'''
	Sets up the environment variables for persistent storage.
	'''
	persistent_storage = os.getenv('APP_PERSISTENT_STORAGE', 'persistent_storage')

	vector_db_dir = os.path.join(persistent_storage, 'vector_db_data')
	if not os.path.exists(vector_db_dir):
		os.makedirs(vector_db_dir, 0o750, True)

	model_dir = os.path.join(persistent_storage, 'model_files')
	if not os.path.exists(model_dir):
		os.makedirs(model_dir, 0o750, True)

	os.environ['APP_PERSISTENT_STORAGE'] = persistent_storage
	os.environ['VECTORDB_DIR'] = vector_db_dir
	os.environ['MODEL_DIR'] = model_dir
	os.environ['SENTENCE_TRANSFORMERS_HOME'] = os.getenv('SENTENCE_TRANSFORMERS_HOME', model_dir)
	os.environ['TRANSFORMERS_CACHE'] = os.getenv('TRANSFORMERS_CACHE', model_dir)


_setup_env_vars()

# todo: print all set env vars
print('Environment variables:')
print(os.environ['APP_PERSISTENT_STORAGE'])
print(os.environ['VECTORDB_DIR'])
print(os.environ['MODEL_DIR'])
print(os.environ['SENTENCE_TRANSFORMERS_HOME'])
print(os.environ['TRANSFORMERS_CACHE'])

app.extra['CONFIG'] = get_config()
app.extra['ENABLED'] = model_init(app)
print('App', 'enabled' if app.extra['ENABLED'] else 'disabled', 'at startup')
