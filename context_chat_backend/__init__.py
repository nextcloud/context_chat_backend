from os import getenv

from dotenv import load_dotenv
import uvicorn

from .controller import app
from .download import model_init
from .models import models
from .utils import to_int
from .vectordb import vector_dbs

load_dotenv()

__all__ = ['create_server', 'vector_dbs', 'models']


def create_server(config: dict[str, tuple[str, dict]]):
	'''
	Creates a FastAPI server with the given config.

	Args
	----
	config: dict
		A dictionary containing the services to be deployed.
	'''
	app.extra['CONFIG'] = config
	app.extra['ENABLED'] = model_init(app)

	uvicorn.run(
		app=app,
		host=getenv('APP_HOST', '0.0.0.0'),
		port=to_int(getenv('APP_PORT'), 9000),
		http='h11',
		interface='asgi3',
		log_level=('warning', 'debug')[getenv('DEBUG', '0') == '1'],
		use_colors=True,
		limit_concurrency=100,
		backlog=100,
		timeout_keep_alive=10,
		h11_max_incomplete_event_size=5 * 1024 * 1024,  # 5MB
	)
