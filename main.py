#!/usr/bin/env python3

import logging
from json import dumps
from multiprocessing import set_start_method
from os import getenv

import uvicorn
from nc_py_api.ex_app import setup_nextcloud_logging

from context_chat_backend import app  # isort: skip
from context_chat_backend.utils import to_int  # isort: skip

if __name__ == '__main__':
	app_config = app.extra['CONFIG']
	enabled = app.extra['ENABLED']

	# set_start_method('fork', force=True)

	APP_ID = getenv('APP_ID', 'context_chat_backend')
	logger = logging.getLogger(APP_ID)
	logger.setLevel(('WARNING', 'DEBUG')[app_config['debug']])
	setup_nextcloud_logging(APP_ID, logging.WARNING)

	print('App config:\n' + dumps(app_config, indent=2), flush=True)
	print('\n\nApp', 'enabled' if app.extra['ENABLED'] else 'disabled', 'at startup', flush=True)

	uvicorn.run(
		app='context_chat_backend:app',
		host=getenv('APP_HOST', '127.0.0.1'),
		port=to_int(getenv('APP_PORT'), 9000),
		http='h11',
		interface='asgi3',
		log_level=('warning', 'trace')[app_config['debug']],
		use_colors=bool(app_config['use_colors'] and getenv('CI', 'false') == 'false'),
		# limit_concurrency=10,
		# backlog=20,
		timeout_keep_alive=120,
		h11_max_incomplete_event_size=5 * 1024 * 1024,  # 5MiB
		# todo: on-demand instantiation of the resources for multi-worker mode
		workers=app_config['uvicorn_workers'],
	)
