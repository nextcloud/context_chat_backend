from hashlib import file_digest
from logging import error as log_error
from pathlib import Path
import os
import re
import shutil
import tarfile
import zipfile

from dotenv import load_dotenv
from fastapi import FastAPI
import requests

load_dotenv()

_MODELS_DIR = os.getenv('MODEL_DIR', 'persistent_storage/model_files')
_BASE_URL = os.getenv(
	'DOWNLOAD_URI',
	'https://download.nextcloud.com/server/apps/context_chat_backend'
).removesuffix('/') + '/'
_DEFAULT_EXT = '.tar.gz'
_KNOWN_EXTENSIONS = (
	'gguf',
	'h5',
	'pt',
	'bin',
	'json',
	'txt',
	'pkl',
	'pickle',
	'safetensors',
	'tar.gz',
	'tar.bz2',
	'tar.xz',
	'zip',
)
_KNOWN_ARCHIVES = (
	'.tar.gz',
	'.tar.bz2',
	'.tar.xz',
	'.zip',
)

_model_config: dict[str, str | None] = {
	'hkunlp/instructor-base': ('hkunlp_instructor-base', '.tar.gz', '19751ec112564f2c568b96a794dd4a16f335ee42b2535a890b577fc5137531eb'),  # noqa: E501
	'dolphin-2.2.1-mistral-7b.Q5_K_M.gguf': ('dolphin-2.2.1-mistral-7b.Q5_K_M.gguf', '', '591a9b807bfa6dba9a5aed1775563e4364d7b7b3b714fc1f9e427fa0e2bf6ace'),  # noqa: E501
}


def _get_model_name_or_path(config: dict, model_type: str) -> str | None:
	if (model_config := config.get(model_type)) is not None:
		model_config = model_config[1]
		return (
			model_config.get('model_name')
			or model_config.get('model_path')
			or model_config.get('model_id')
			or model_config.get('model_file')
			or model_config.get('model')
		)


def _set_app_config(app: FastAPI, config: dict[str, tuple[str, dict]]):
	'''
	Sets the app config as an extra attribute to the app object.

	Args
	----
	app: FastAPI
		The FastAPI app object
	config: dict
		A dictionary containing the services to be deployed.
	'''
	if config.get('embedding'):
		from .models import init_model

		model = init_model('embedding', config.get('embedding'))
		app.extra['EMBEDDING_MODEL'] = model

	if config.get('vectordb'):
		from .vectordb import get_vector_db

		client_klass = get_vector_db(config.get('vectordb')[0])

		if app.extra.get('EMBEDDING_MODEL') is not None:
			app.extra['VECTOR_DB'] = client_klass(app.extra['EMBEDDING_MODEL'], **config.get('vectordb')[1])
		else:
			app.extra['VECTOR_DB'] = client_klass(**config.get('vectordb')[1])

	if config.get('llm'):
		from .models import init_model

		llm_name, llm_config = config.get('llm')
		app.extra['LLM_TEMPLATE'] = llm_config.pop('template', '')

		model = init_model('llm', (llm_name, llm_config))
		app.extra['LLM_MODEL'] = model


def _model_exists(model_name_or_path: str) -> bool:
	if os.path.exists(model_name_or_path):
		return True

	if os.path.exists(Path(_MODELS_DIR, model_name_or_path)):
		return True

	if (extracted_name := _model_config.get(model_name_or_path)) is not None \
		and os.path.exists(Path(_MODELS_DIR, extracted_name[0])):
		return True

	return False


def _download_model(model_name_or_path: str) -> bool:
	if not model_name_or_path:
		log_error('Error: Model name or path not specified')
		return False

	if _model_exists(model_name_or_path):
		return True

	if model_name_or_path.startswith('/'):
		model_name = os.path.basename(model_name_or_path)
	else:
		model_name = re.sub(r'^.*' + _MODELS_DIR + r'/', '', model_name_or_path)

	if model_name in _model_config.keys():
		model_file = _model_config[model_name][0] + _model_config[model_name][1]
		url = _BASE_URL + model_file
		filepath = Path(_MODELS_DIR, model_file).as_posix()
	elif model_name.endswith(_KNOWN_EXTENSIONS):
		url = _BASE_URL + model_name
		filepath = Path(_MODELS_DIR, model_name).as_posix()
	else:
		url = _BASE_URL + model_name + _DEFAULT_EXT
		filepath = Path(_MODELS_DIR, model_name + _DEFAULT_EXT).as_posix()

	try:
		f = open(filepath, 'w+b')
		r = requests.get(url, stream=True)
		r.raw.decode_content = True  # content decompression

		if r.status_code >= 400:
			log_error(f"Error: Network error while downloading '{url}': {r}")
			return False

		shutil.copyfileobj(r.raw, f, length=16 * 1024 * 1024)  # 16MB chunks

		# hash check if the config is declared
		if model_name in _model_config.keys():
			f.seek(0)
			original_digest = _model_config.get(model_name, (None, None, None))[2]
			digest = file_digest(f, 'sha256').hexdigest()
			if (original_digest != digest):
				log_error(
					f'Error: Model file ({filepath}) corrupted:\nexpected hash {original_digest}\ngot {digest}'
				)
				return False

		f.close()

		return _extract_n_save(model_name, filepath)
	except OSError as e:
		log_error(e)
		return False


def _extract_n_save(model_name: str, filepath: str) -> bool:
	if not os.path.exists(filepath):
		log_error('Error: Model file not found after successful download. This should not happen.')
		return False

	# extract the model if it is a compressed file
	if (filepath.endswith(_KNOWN_ARCHIVES)):
		try:
			if filepath.endswith('.tar.gz'):
				tar = tarfile.open(filepath, 'r:gz')
			elif filepath.endswith('.tar.bz2'):
				tar = tarfile.open(filepath, 'r:bz2')
			elif filepath.endswith('.tar.xz'):
				tar = tarfile.open(filepath, 'r:xz')
			else:
				tar = zipfile.ZipFile(filepath, 'r')

			tar.extractall(_MODELS_DIR)
			tar.close()
			os.remove(filepath)
		except OSError as e:
			log_error(f'Error: Model extraction failed: {e}')
			return False

		return True

	model_name = re.sub(r'^.*' + _MODELS_DIR + r'/', '', model_name)
	try:
		os.rename(filepath, Path(_MODELS_DIR, model_name).as_posix())
		return True
	except OSError as e:
		log_error(f'Error: File move into `{_MODELS_DIR}` failed: {e}')
		return False


async def download_all_models(app: FastAPI, update_progress: callable):
	'''
	Downloads all models specified in the config.yaml file
	and sets the required keys in the app object.

	Args
	----
	app: FastAPI object
	'''
	config = app.extra['CONFIG']

	if os.getenv('DISABLE_CUSTOM_DOWNLOAD_URI', '0') == '1':
		await update_progress(100)
		_set_app_config(app, config)
		return

	progress = 0
	for model_type in ('embedding', 'llm'):
		model_name = _get_model_name_or_path(config, model_type)
		if not _download_model(model_name):
			raise Exception(f'Error: Model download failed for {model_name}')
		await update_progress(progress := progress + 50)

	_set_app_config(app, config)


def model_init(app: FastAPI) -> bool:
	for model_type in ('embedding', 'llm'):
		model_name = _get_model_name_or_path(app.extra['CONFIG'], model_type)
		if not _model_exists(model_name):
			return False

	_set_app_config(app, app.extra['CONFIG'])
	return True
