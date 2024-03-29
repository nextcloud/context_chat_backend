import os
import shutil
from json import dumps

from dotenv import load_dotenv

from .config_parser import get_config
from .download import model_init
from .utils import to_int

load_dotenv()

__all__ = ['app', 'app_config', 'to_int']


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

	config_path = os.path.join(persistent_storage, 'config.yaml')
	if not os.path.exists(config_path):
		if not os.path.exists('config.yaml'):
			raise AssertionError(f'Error: sample config file (/config.yaml) and the provided config file ({config_path}) do not exist')  # noqa: E501

		shutil.move('config.yaml', config_path)

	os.environ['APP_PERSISTENT_STORAGE'] = persistent_storage
	os.environ['VECTORDB_DIR'] = vector_db_dir
	os.environ['MODEL_DIR'] = model_dir
	os.environ['SENTENCE_TRANSFORMERS_HOME'] = os.getenv('SENTENCE_TRANSFORMERS_HOME', model_dir)
	os.environ['TRANSFORMERS_CACHE'] = os.getenv('TRANSFORMERS_CACHE', model_dir)
	os.environ['CC_CONFIG_PATH'] = os.getenv('CC_CONFIG_PATH', config_path)


_setup_env_vars()

app_config = get_config(os.environ['CC_CONFIG_PATH'])
print('App config:\n' + dumps(app_config, indent=2), flush=True)

from .controller import app  # noqa: E402

app.extra['CONFIG'] = app_config
app.extra['ENABLED'] = model_init(app)

print('\n\nApp', 'enabled' if app.extra['ENABLED'] else 'disabled', 'at startup', flush=True)
