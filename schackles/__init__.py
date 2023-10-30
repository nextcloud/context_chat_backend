from dotenv import load_dotenv
from os import getenv
import uvicorn

from .utils import value_of, to_int
from .vectordb import vector_dbs
from .models import models
from .controller import app

load_dotenv()

__all__ = ["create_server", "value_of", "vector_dbs", "models"]


def create_server(services: dict, args: dict):
	"""
	Creates a flask server with the given services and arguments.

	Args
	----
	services: dict
		A dictionary containing the services to be deployed.
	args: ArgumentParser
		An ArgumentParser object containing the command line arguments.
	"""
	if services["vector_db"]:
		from .vectordb import get_vector_db

		client_klass = get_vector_db(args.vector_db)
		app.extra["VECTOR_DB"] = client_klass()

	if services["embedding_model"]:
		from .models import init_model

		model = init_model("embedding", args.embedding_model)
		app.extra["EMBEDDING_MODEL"] = model()

	if services["llm_model"]:
		from .models import init_model

		model = init_model("llm", args.llm_model)
		app.extra["LLM_MODEL"] = model()

	uvicorn.run(
		app=app,
		port=to_int(getenv("UVICORN_PORT")) if value_of(getenv("UVICORN_PORT")) else 9000,
		http="h11",
		interface="asgi3",
		log_level="info",
		use_colors=True,
		limit_concurrency=100,
		backlog=100,
		timeout_keep_alive=10,
		h11_max_incomplete_event_size=5 * 1024 * 1024,  # 5MB
	)
