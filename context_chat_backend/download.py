from logging import error as log_error
from pathlib import Path
import os
import re
import shutil
import tarfile
import zipfile

from dotenv import load_dotenv
import requests

load_dotenv()

_MODELS_DIR = 'model_files'
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

_model_names: dict[str, str | None] = {
	'hkunlp/instructor-base': ('hkunlp_instructor-base', '.tar.gz'),
	'dolphin-2.2.1-mistral-7b.Q5_K_M.gguf': ('dolphin-2.2.1-mistral-7b.Q5_K_M.gguf', ''),
}


def download_all_models(config: dict) -> str | None:
	'''
	Downloads all models specified in the config.yaml file

	Args
	----
	config: dict
		config.yaml loaded as a dict

	Returns
	-------
	str | None
		The name of the model that failed to download, if any
	'''
	for model_type in ('embedding', 'llm'):
		if (model_config := config.get(model_type)) is not None:
			model_config = model_config[1]
			model_name = (
				model_config.get('model_name')
				or model_config.get('model_path')
				or model_config.get('model_id')
				or model_config.get('model_file')
				or model_config.get('model')
			)
			if not _download_model(model_name):
				return model_name

	return None


def _download_model(model_name_or_path: str) -> bool:
	if not model_name_or_path:
		log_error('Error: Model name or path not specified')
		return False

	# TODO: hash check
	if os.path.exists(model_name_or_path):
		return True

	if (extracted_name := _model_names.get(model_name_or_path)) is not None \
		and os.path.exists(Path(_MODELS_DIR, extracted_name[0])):
		return True

	model_name = re.sub(r'^.*' + _MODELS_DIR + r'/', '', model_name_or_path)

	if model_name in _model_names.keys():
		model_file = _model_names[model_name][0] + _model_names[model_name][1]
		url = _BASE_URL + model_file
		filepath = Path(_MODELS_DIR, model_file).as_posix()
	elif model_name.endswith(_KNOWN_EXTENSIONS):
		url = _BASE_URL + model_name
		filepath = Path(_MODELS_DIR, model_name).as_posix()
	else:
		url = _BASE_URL + model_name + _DEFAULT_EXT
		filepath = Path(_MODELS_DIR, model_name + _DEFAULT_EXT).as_posix()

	try:
		f = open(filepath, 'wb')
		r = requests.get(url, stream=True)
		r.raw.decode_content = True  # content decompression

		if r.status_code >= 400:
			log_error(f"Error: Network error while downloading '{url}': {r}")
			return False

		shutil.copyfileobj(r.raw, f, length=16 * 1024 * 1024)  # 16MB chunks
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
