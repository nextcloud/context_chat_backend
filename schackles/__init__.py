from os import getenv

from dotenv import load_dotenv
import uvicorn

from .controller import app
from .models import models
from .utils import to_int, value_of
from .vectordb import vector_dbs

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
	if services.get("embedding_model"):
		from .models import init_model

		model = init_model("embedding", args.embedding_model)
		app.extra["EMBEDDING_MODEL"] = model

	if services.get("vector_db"):
		from .vectordb import get_vector_db

		client_klass = get_vector_db(args.vector_db)

		if app.extra.get("EMBEDDING_MODEL") is not None:
			app.extra["VECTOR_DB"] = client_klass(app.extra["EMBEDDING_MODEL"])
		else:
			app.extra["VECTOR_DB"] = client_klass()

	if services.get("llm_model"):
		from .models import init_model

		model = init_model("llm", args.llm_model)
		app.extra["LLM_MODEL"] = model

	uvicorn.run(
		app=app,
		host=getenv("APP_HOST", "0.0.0.0"),
		port=to_int(getenv("APP_PORT"), 9000),
		http="h11",
		interface="asgi3",
		log_level=("warning", "debug")[getenv("DEBUG", "0") == "1"],
		use_colors=True,
		limit_concurrency=100,
		backlog=100,
		timeout_keep_alive=10,
		h11_max_incomplete_event_size=5 * 1024 * 1024,  # 5MB
	)
