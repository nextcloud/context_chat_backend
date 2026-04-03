#!/usr/bin/env python3
#
# SPDX-FileCopyrightText: 2023 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#

import logging
from os import cpu_count, getenv

import psutil
import uvicorn
from nc_py_api.ex_app import run_app

from context_chat_backend.types import TConfig  # isort: skip
from context_chat_backend.controller import app  # isort: skip
from context_chat_backend.logger import get_logging_config, setup_logging  # isort: skip
from context_chat_backend.utils import redact_config  # isort: skip

LOGGER_CONFIG_NAME = 'logger_config.yaml'

def _setup_log_levels(debug: bool):
	'''
	Set log levels for the modules at once for a cleaner usage later.
	'''
	if not debug:
		# warning is the default level
		return

	LOGGERS = (
		'ccb',
		'ccb.chain',
		'ccb.doc_loader',
		'ccb.injest',
		'ccb.models',
		'ccb.vectordb',
		'ccb.controller',
		'ccb.dyn_loader',
		'ccb.ocs_utils',
		'ccb.utils',
	)

	for name in LOGGERS:
		logger = logging.getLogger(name)
		logger.setLevel(logging.DEBUG)


if __name__ == '__main__':
	import multiprocessing as mp

	logging_config = get_logging_config(LOGGER_CONFIG_NAME)
	setup_logging(logging_config)
	app_config: TConfig = app.extra['CONFIG']
	_setup_log_levels(app_config.debug)

	# do forks from a clean process that doesn't have any threads or locks
	mp.set_start_method('forkserver')
	mp.set_forkserver_preload([
		'context_chat_backend.chain.ingest.injest',
		'context_chat_backend.vectordb.pgvector',
		'langchain',
		'logging',
		'numpy',
		'sqlalchemy',
	])

	print(f'CPU count: {cpu_count()}, Memory: {psutil.virtual_memory()}')
	print('App config:\n' + redact_config(app_config).model_dump_json(indent=2), flush=True)

	uv_log_config = uvicorn.config.LOGGING_CONFIG  # pyright: ignore[reportAttributeAccessIssue]
	uv_log_config['formatters']['json'] = logging_config['formatters']['json']
	uv_log_config['handlers']['file_json'] = logging_config['handlers']['file_json']

	uv_log_config['loggers']['uvicorn']['handlers'].append('file_json')
	uv_log_config['loggers']['uvicorn.access']['handlers'].append('file_json')

	run_app(
		uvicorn_app=app,
		http='h11',
		interface='asgi3',
		log_config=uv_log_config,
		log_level=app_config.uvicorn_log_level,
		use_colors=bool(app_config.use_colors and getenv('CI', 'false') == 'false'),
		# limit_concurrency=10,
		# backlog=20,
		timeout_keep_alive=120,
		h11_max_incomplete_event_size=5 * 1024 * 1024,  # 5MiB
		workers=app_config.uvicorn_workers,
	)
