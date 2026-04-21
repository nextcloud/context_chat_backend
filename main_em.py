#!/usr/bin/env python3
#
# SPDX-FileCopyrightText: 2024 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
import logging
import os
from base64 import b64encode
from time import sleep
from urllib.parse import quote_plus, urlparse

import niquests
import uvicorn

from context_chat_backend.types import DEFAULT_EM_MODEL_ALIAS, AppRole  # isort: skip
from context_chat_backend.config_parser import get_config  # isort: skip
from context_chat_backend.logger import get_logging_config, setup_logging  # isort: skip
from context_chat_backend.setup_functions import ensure_config_file, setup_env_vars  # isort: skip
from context_chat_backend.utils import get_app_role, is_k8s_env, redact_config	# isort: skip


LOGGER_CONFIG_NAME = 'logger_config_em.yaml'
LOGGER_K8S_CONFIG_NAME = 'logger_config.k8s.yaml'
STARTUP_CHECK_SEC = 10
MAX_TRIES = 180  # 180*10 secs = 30 minutes max


def _get_main_app_client() -> niquests.Session:
	"""
	Get a niquests Session to connect to the main app, depending on the deployment type.
	Returns
	-------
		niquests.Session: The niquests Session.
	"""
	if os.getenv('HP_SHARED_KEY'):
		base_url = 'http+unix://' + quote_plus(os.getenv('HP_EXAPP_SOCK', '/tmp/exapp.sock'))  # noqa: S108
	else:
		connect_host = 'localhost' if os.environ['APP_HOST'] in ('0.0.0.0', '::') else os.environ['APP_HOST']  # noqa: S104
		base_url = f'http://{connect_host}:{os.environ["APP_PORT"]}'

	return niquests.Session(base_url=base_url, headers={
		'EX-APP-ID': os.getenv('APP_ID', 'context_chat_backend'),
		'EX-APP-VERSION': os.getenv('APP_VERSION', ''),
		'OCS-APIRequest': 'true',
		'AUTHORIZATION-APP-API': b64encode(f':{os.getenv("APP_SECRET", "")}'.encode()).decode('utf-8'),
	})


def _wait_main_app_enabled() -> None:
	'''
	Raises
	------
	RuntimeError: If the main app is not enabled/ready within the expected time.
	niquests.RequestException: If there is an error while making the request to the main app
	'''
	_max_tries = MAX_TRIES
	_last_err = None
	client = _get_main_app_client()

	# wait for the main process to be ready
	while _max_tries > 0:
		try:
			response = client.get('/enabled')
			response.raise_for_status()
			enabled = response.json().get('enabled', False)
			if enabled:
				return
			print(
				f'{(MAX_TRIES-_max_tries+1)*STARTUP_CHECK_SEC}/{MAX_TRIES*STARTUP_CHECK_SEC} secs:'
				f' [Embedding server] Waiting for the main app to be enabled/ready. Current enabled state: {enabled}',
				flush=True,
			)
		except niquests.RequestException as e:
			print(
				f'{(MAX_TRIES-_max_tries+1)*STARTUP_CHECK_SEC}/{MAX_TRIES*STARTUP_CHECK_SEC} secs:'
				f' [Embedding server] Waiting for the main app to be enabled/ready, errors are expected initially: {e}',
				flush=True,
			)
			if _max_tries == 1:
				_last_err = e
		except Exception as e:
			raise RuntimeError('Unexpected error while waiting for the main app to be enabled/ready') from e
		finally:
			sleep(STARTUP_CHECK_SEC)
			_max_tries -= 1

	# if we exhausted all tries
	raise _last_err or RuntimeError('Timed out waiting for the main app to be enabled/ready.')


if __name__ == '__main__':
	app_role = get_app_role()
	if app_role == AppRole.UP:
		print('Internal embedding server is not required for the Updates Processing role, stopping this process.')
		exit(0)

	# intial buffer
	print(
		f'Waiting for {STARTUP_CHECK_SEC} seconds before starting embedding server to allow main app to start',
		flush=True,
	)
	sleep(STARTUP_CHECK_SEC)

	setup_env_vars()
	ensure_config_file()
	app_config = get_config(os.environ['CC_CONFIG_PATH'])
	em_conf = app_config.embedding

	if em_conf.workers <= 0 or em_conf.remote_service:
		print('Exiting embedding server as it is not configured to run locally.', flush=True)
		exit(0)

	# redact sensitive info before logging, although no api key or password should be present
	# in local embedding server config
	print('Embedder config:\n' + redact_config(em_conf).model_dump_json(indent=2), flush=True)

	k8s_env = is_k8s_env()
	logging_config = get_logging_config(LOGGER_K8S_CONFIG_NAME if k8s_env else LOGGER_CONFIG_NAME)
	setup_logging(logging_config)
	logger = logging.getLogger('emserver')
	if app_config.debug:
		logger.setLevel(logging.DEBUG)

	try:
		_wait_main_app_enabled()
	except Exception as e:
		logger.error(
			'Failed waiting for the main app to be enabled. This could indicate an issue with the AppAPI'
			' Deploy Daemon setup or some issue in the main app setup. Some common causes of the latter'
			' could be no/no stable internet connection to download the required models, disk space full,'
			' or this app not being able to contact the Nextcloud server to report progress of the model'
			' download.',
			exc_info=e,
		)
		exit(1)

	# update model path to be in the persistent storage if it is not already valid
	if 'model' not in em_conf.llama:
		raise ValueError('Error: "model" key not found in embedding->llama\'s config')

	if not os.path.isfile(em_conf.llama['model']):
		em_conf.llama['model'] = os.path.join(
			os.getenv('APP_PERSISTENT_STORAGE', 'persistent_storage'),
			'model_files',
			em_conf.llama['model'],
		)
		logger.debug(f'Trying model path: {em_conf.llama["model"]}')

		# if the model file is still not found, raise an error
		if not os.path.isfile(em_conf.llama['model']):
			raise ValueError('Error: Model file not found at the updated path')

	# delayed import for libcuda.so.1 to be available
	from llama_cpp.server.app import create_app
	from llama_cpp.server.settings import ModelSettings, ServerSettings

	base_url = urlparse(em_conf.base_url)
	host = base_url.hostname or '127.0.0.1'
	port = base_url.port or 5000
	server_settings = ServerSettings(host=host, port=port)
	model_settings = [ModelSettings(model_alias=DEFAULT_EM_MODEL_ALIAS, embedding=True, **em_conf.llama)]
	app = create_app(
		server_settings=server_settings,
		model_settings=model_settings,
	)

	uv_log_config = uvicorn.config.LOGGING_CONFIG  # pyright: ignore[reportAttributeAccessIssue]
	use_colors = False if k8s_env else (app_config.use_colors and os.getenv('CI', 'false') == 'false')

	if k8s_env:
		uv_log_config['formatters']['default'] = logging_config['formatters']['json']
		uv_log_config['formatters']['access'] = logging_config['formatters']['json']
	else:
		uv_log_config['formatters']['json'] = logging_config['formatters']['json']
		uv_log_config['handlers']['file_json'] = logging_config['handlers']['file_json']
		uv_log_config['loggers']['uvicorn']['handlers'].append('file_json')
		uv_log_config['loggers']['uvicorn.access']['handlers'].append('file_json')

	uvicorn.run(
		# todo: use string import of the app
		app=app,
		host=host,
		port=port,
		http='h11',
		interface='asgi3',
		log_config=uv_log_config,
		log_level=app_config.uvicorn_log_level,
		use_colors=use_colors,
		workers=em_conf.workers,
	)
