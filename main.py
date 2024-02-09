#!/usr/bin/env python3
import os

import uvicorn

from context_chat_backend.utils import to_int

if __name__ == '__main__':
	uvicorn.run(
		app='context_chat_backend:app',
		host=os.getenv('APP_HOST', '0.0.0.0'),
		port=to_int(os.getenv('APP_PORT'), 9000),
		http='h11',
		interface='asgi3',
		# todo
		# log_level=('warning', 'debug')[os.getenv('DEBUG', '0') == '1'],
		log_level='debug',
		use_colors=True,
		limit_concurrency=100,
		backlog=100,
		timeout_keep_alive=20,
		h11_max_incomplete_event_size=5 * 1024 * 1024,  # 5MB
		workers=to_int(os.getenv('UVICORN_WORKERS'), 1),
	)
