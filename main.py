#!/usr/bin/env python3
#
# SPDX-FileCopyrightText: 2023 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
import logging
from os import getenv

import uvicorn

from context_chat_backend.types import TConfig  # isort: skip
from context_chat_backend.controller import app  # isort: skip
from context_chat_backend.utils import to_int  # isort: skip
from context_chat_backend.logger import get_logging_config, setup_logging  # isort: skip

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
	logging_config = get_logging_config()
	setup_logging(logging_config)
	app_config: TConfig = app.extra['CONFIG']
	_setup_log_levels(app_config.debug)

	print('App config:\n' + app_config.model_dump_json(indent=2), flush=True)

	uv_log_config = uvicorn.config.LOGGING_CONFIG  # pyright: ignore[reportAttributeAccessIssue]
	uv_log_config['formatters']['json'] = logging_config['formatters']['json']
	uv_log_config['handlers']['file_json'] = logging_config['handlers']['file_json']

	uv_log_config['loggers']['uvicorn']['handlers'].append('file_json')
	uv_log_config['loggers']['uvicorn.access']['handlers'].append('file_json')

	uvicorn.run(
		app=app,
		host=getenv('APP_HOST', '127.0.0.1'),
		port=to_int(getenv('APP_PORT'), 9000),
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
