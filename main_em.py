#!/usr/bin/env python3

import json
import os
import signal
import threading
import time

import uvicorn
from llama_cpp.server.app import create_app
from llama_cpp.server.settings import ModelSettings, ServerSettings
from starlette.datastructures import URL
from starlette.types import ASGIApp, Receive, Scope, Send

from context_chat_backend.config_parser import TConfig, get_config  # isort: skip
from context_chat_backend.setup_functions import ensure_config_file, setup_env_vars  # isort: skip


last_time_lock = threading.Lock()
last_time = 0
holding_cnt = 0

def die_on_time(app_config: TConfig):
	global last_time
	while True:
		time.sleep(60)
		with last_time_lock:
			if holding_cnt <= 0 and time.time() - last_time > app_config['embedding']['offload_after_mins'] * 60:
				print('Killing the embedding server due to inactivity', flush=True)
				os.kill(os.getpid(), signal.SIGKILL)


class LastAccessMiddleware:
	'''
	Records last access time of the request to the embeddings route.
	'''
	def __init__(self, app: ASGIApp) -> None:
		self.app = app

	async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
		global last_time, holding_cnt
		if scope['type'] != 'http':
			await self.app(scope, receive, send)
			return

		url = URL(scope=scope)

		if url.path == '/heartbeat':
			await send({'type': 'http.response.start', 'status': 200})
			await send({'type': 'http.response.body', 'body': b'OK'})
			return

		if url.path == '/v1/embeddings':
			try:
				with last_time_lock:
					holding_cnt += 1
				await self.app(scope, receive, send)
			finally:
				with last_time_lock:
					last_time = time.time()
					holding_cnt -= 1


if __name__ == '__main__':
	# todo
	setup_env_vars()
	ensure_config_file()

	app_config = get_config(os.environ['CC_CONFIG_PATH'])
	print('Embedder config:\n' + json.dumps(app_config['embedding'], indent=2), flush=True)

	# update model path to be in the persistent storage if it is not already valid
	if 'model' not in app_config['embedding']['llama']:
		raise ValueError('Error: "model" key not found in embedding->llama\'s config')

	if not os.path.isfile(app_config['embedding']['llama']['model']):
		app_config['embedding']['llama']['model'] = os.path.join(
			os.getenv('APP_PERSISTENT_STORAGE', 'persistent_storage'),
			'model_files',
			app_config['embedding']['llama']['model'],
		)

		# if the model file is still not found, raise an error
		if not os.path.isfile(app_config['embedding']['llama']['model']):
			raise ValueError('Error: Model file not found at the updated path')

	server_settings = ServerSettings(
		host=app_config['embedding']['host'],
		port=app_config['embedding']['port'],
	)
	model_settings = [ModelSettings(model_alias='em_model', embedding=True, **app_config['embedding']['llama'])]
	app = create_app(
		server_settings=server_settings,
		model_settings=model_settings,
	)
	app.add_middleware(LastAccessMiddleware)

	# start the last time thread
	last_time_thread = threading.Thread(target=die_on_time, args=(app_config,))
	last_time_thread.start()
	with last_time_lock:
		last_time = time.time()

	uvicorn.run(
		app=app,
		host=server_settings.host,
		port=server_settings.port,
		http='h11',
		interface='asgi3',
		# todo
		log_level=('warning', 'trace')[app_config['debug']],
		use_colors=bool(app_config['use_colors'] and os.getenv('CI', 'false') == 'false'),
		workers=app_config['embedding']['workers'],
	)
