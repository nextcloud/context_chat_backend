#!/usr/bin/env python3

from os import getenv

import uvicorn

from context_chat_backend.controller import app  # isort: skip
from context_chat_backend.utils import to_int  # isort: skip
from context_chat_backend.config_parser import TConfig  # isort: skip

if __name__ == '__main__':
	app_config: TConfig = app.extra['CONFIG']

	print('App config:\n' + app_config.model_dump_json(indent=2), flush=True)

	uvicorn.run(
		app=app,
		host=getenv('APP_HOST', '127.0.0.1'),
		port=to_int(getenv('APP_PORT'), 9000),
		http='h11',
		interface='asgi3',
		log_level=('warning', 'trace')[app_config.debug],
		use_colors=bool(app_config.use_colors and getenv('CI', 'false') == 'false'),
		# limit_concurrency=10,
		# backlog=20,
		timeout_keep_alive=120,
		h11_max_incomplete_event_size=5 * 1024 * 1024,  # 5MiB
		# todo: on-demand instantiation of the resources for multi-worker mode
		workers=app_config.uvicorn_workers,
	)
