#!/usr/bin/env python3
#
# SPDX-FileCopyrightText: 2024 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
import logging
import os
from time import sleep

import httpx
import uvicorn

from context_chat_backend.config_parser import get_config  # isort: skip
from context_chat_backend.logger import get_logging_config, setup_logging  # isort: skip
from context_chat_backend.ocs_utils import sign_request  # isort: skip
from context_chat_backend.setup_functions import ensure_config_file, setup_env_vars  # isort: skip


LOGGER_CONFIG_NAME = 'logger_config_em.yaml'
# todo: config and env var for this
MODEL_ALIAS = 'em_model'
STARTUP_CHECK_SEC = 10
MAX_TRIES = 180  # 30 minutes max


if __name__ == '__main__':
	# intial buffer
	sleep(STARTUP_CHECK_SEC)

	setup_env_vars()
	ensure_config_file()
	app_config = get_config(os.environ['CC_CONFIG_PATH'])
	em_conf = app_config.embedding

	if em_conf.workers <= 0:
		print('No embedding workers configured, exiting...', flush=True)
		exit(0)

	print('Embedder config:\n' + em_conf.model_dump_json(indent=2), flush=True)

	logging_config = get_logging_config(LOGGER_CONFIG_NAME)
	setup_logging(logging_config)
	logger = logging.getLogger('emserver')
	if app_config.debug:
		logger.setLevel(logging.DEBUG)

	_max_tries = MAX_TRIES
	_enabled = False
	_last_err = None
	_headers = {}
	sign_request(_headers)
	# wait for the main process to be ready, check the /enabled endpoint
	while _max_tries > 0:
		with httpx.Client() as client:
			try:
				ret = client.get(f'http://{os.environ["APP_HOST"]}:{os.environ["APP_PORT"]}/enabled', headers=_headers)
				ret.raise_for_status()

				if not ret.json().get('enabled', False):
					raise RuntimeError('Main app is not enabled, sleeping for a while...')
			except (httpx.RequestError, RuntimeError) as e:
				print(f'{MAX_TRIES-_max_tries+1}/{MAX_TRIES}: Error checking main app status: {e}', flush=True)
				_last_err = e
				sleep(STARTUP_CHECK_SEC)
				_max_tries -= 1
				continue

			_enabled = True
			break

	if not _enabled:
		logger.error('Failed waiting for the main app to be enabled, exiting...', exc_info=_last_err)
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

	server_settings = ServerSettings(
		host=em_conf.host,
		port=em_conf.port,
	)
	model_settings = [ModelSettings(model_alias=MODEL_ALIAS, embedding=True, **em_conf.llama)]
	app = create_app(
		server_settings=server_settings,
		model_settings=model_settings,
	)

	uv_log_config = uvicorn.config.LOGGING_CONFIG  # pyright: ignore[reportAttributeAccessIssue]
	uv_log_config['formatters']['json'] = logging_config['formatters']['json']
	uv_log_config['handlers']['file_json'] = logging_config['handlers']['file_json']

	uv_log_config['loggers']['uvicorn']['handlers'].append('file_json')
	uv_log_config['loggers']['uvicorn.access']['handlers'].append('file_json')

	uvicorn.run(
		# todo: use string import of the app
		app=app,
		host=em_conf.host,
		port=em_conf.port,
		http='h11',
		interface='asgi3',
		log_config=uv_log_config,
		log_level=app_config.uvicorn_log_level,
		use_colors=bool(app_config.use_colors and os.getenv('CI', 'false') == 'false'),
		workers=em_conf.workers,
	)
