import os
import shutil
import tarfile
import zipfile
from logging import error as log_error
from pathlib import Path

import requests

_BASE_URL = 'https://download.nextcloud.com/server/apps/schackles/'
_DEFAULT_EXT = '.tar.gz'
_KNOWN_EXTENSIONS = [
	'h5',
	'pt',
	'bin',
	'json',
	'txt',
	'pkl',
	'pickle',
	'safetensors'
	'tar.gz',
	'tar.bz2',
	'tar.xz',
	'zip',
]

_model_names: dict[str, str | None] = {
	'hkunlp_instructor-base': 'hkunlp_instructor-base.tar.gz',
	'dolphin-2.2.1-mistral-7b.Q5_K_M.gguf': 'dolphin-2.2.1-mistral-7b.Q5_K_M.gguf',
	'sentence-transformers/all-mpnet-base-v2': 'sentence-transformers_all-mpnet-base-v2.tar.gz',
	'all-MiniLM-L6-v2': 'sentence-transformers_all-MiniLM-L6-v2.tar.gz',
	'gpt2': 'models--gpt2.tar.gz',
}


def download_model(model_name: str) -> bool:
	if model_name not in _model_names.keys():
		log_error(f'Error: Unknown model name {model_name}')
		return False

	# TODO: hash check
	if os.path.exists(Path('./model_files', model_name).as_posix()):
		return True

	model_name = Path(model_name).as_posix().replace('model_files/', '')

	if model_name.split('.')[-1] not in _KNOWN_EXTENSIONS \
		and ''.join(model_name.split('.')[-2:]) not in _KNOWN_EXTENSIONS:
		url = Path(_BASE_URL, model_name, _DEFAULT_EXT).as_posix()
	else:
		url = Path(_BASE_URL, model_name).as_posix()

	filepath = Path('./model_files', model_name).as_posix()

	try:
		f = open(filepath, 'wb')
		r = requests.get(url, stream=True)
		r.raw.decode_content = True  # content decompression

		if r.status_code >= 400:
			log_error(f'Error: Network error while downloading "{url}": {r}')
			return False

		shutil.copyfileobj(r.raw, f, length=16 * 1024 * 1024)  # 16MB chunks
		f.close()

		return _extract_n_save(model_name, filepath)
	except OSError as e:
		print(e)
		return False


def _extract_n_save(model_name: str, filepath: str) -> bool:
	if not os.path.exists(filepath):
		log_error('Error: Model file not found after successful download. This should not happen.')
		return False

	# extract the model if it is a compressed file
	if (
		filepath.endswith('.tar.gz')
		or filepath.endswith('.tar.bz2')
		or filepath.endswith('.tar.xz')
		or filepath.endswith('.zip')
	):
		try:
			if filepath.endswith('.tar.gz'):
				tar = tarfile.open(filepath, 'r:gz')
			elif filepath.endswith('.tar.bz2'):
				tar = tarfile.open(filepath, 'r:bz2')
			elif filepath.endswith('.tar.xz'):
				tar = tarfile.open(filepath, 'r:xz')
			else:
				tar = zipfile.ZipFile(filepath, 'r')

			tar.extractall('./model_files')
			tar.close()
			os.remove(filepath)
		except OSError as e:
			log_error(f'Error: Model extraction failed: {e}')
			return False

		return True

	model_name = Path(model_name).as_posix().replace('model_files/', '')
	try:
		os.rename(filepath, Path('./model_files', model_name).as_posix())
		return True
	except OSError as e:
		log_error(f'Error: File move into `model_files` failed: {e}')
		return False
