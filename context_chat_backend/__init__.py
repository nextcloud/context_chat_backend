import os
import subprocess
from json import dumps

from dotenv import load_dotenv

from .config_parser import get_config
from .download import model_init
from .repair import runner
from .utils import to_int

load_dotenv()

__all__ = ['app', 'app_config', 'to_int']


def _repair_run():
	'''
	Runs the repair script.
	'''
	runner.main()


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

	os.environ['APP_PERSISTENT_STORAGE'] = persistent_storage
	os.environ['VECTORDB_DIR'] = vector_db_dir
	os.environ['MODEL_DIR'] = model_dir
	os.environ['SENTENCE_TRANSFORMERS_HOME'] = os.getenv('SENTENCE_TRANSFORMERS_HOME', model_dir)
	os.environ['HF_HOME'] = os.getenv('HF_HOME', model_dir)
	os.environ['CC_CONFIG_PATH'] = os.getenv('CC_CONFIG_PATH', config_path)


_setup_env_vars()
_repair_run()

# move the correct config file to the persistent storage
subprocess.run(['./hwdetect.sh', 'config'], check=True, shell=False)  # noqa: S603
app_config = get_config(os.environ['CC_CONFIG_PATH'])
print('App config:\n' + dumps(app_config, indent=2), flush=True)

from .controller import app  # noqa: E402

app.extra['CONFIG'] = app_config
app.extra['ENABLED'] = model_init(app)

print('\n\nApp', 'enabled' if app.extra['ENABLED'] else 'disabled', 'at startup', flush=True)
