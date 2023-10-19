#!/usr/bin/env python3

from argparse import ArgumentParser
from dotenv import load_dotenv

from utils import value_of
from vectordb import vector_dbs
from models import models
from controller import app

load_dotenv()


def _create_server(services: dict, args: ArgumentParser):
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
		from vectordb import get_vector_db

		client = get_vector_db(args.vector_db)
		app.config["VECTOR_DB"] = client

	if services["embedding_model"]:
		from models import init_model

		model = init_model("embedding", args.embedding_model)
		app.config["EMBEDDING_MODEL"] = model()

	if services["llm_model"]:
		from models import init_model

		model = init_model("llm", args.llm_model)
		app.config["LLM_MODEL"] = model()

	app.run()


if __name__ == "__main__":
	parser = ArgumentParser(description="Starts a server with the requested services.")

	parser.add_argument(
		"-db",
		"--vector_db",
		type=str,
		choices=vector_dbs,
		help="The vector database to use.",
	)
	parser.add_argument(
		"-em",
		"--embedding_model",
		type=str,
		choices=models["embedding"],
		help="The embedding model to use.",
	)
	parser.add_argument(
		"-lm",
		"--llm_model",
		type=str,
		choices=models["llm"],
		help="The LLM model to use."
	)

	args = parser.parse_args()

	services = {
		"vector_db": False,
		"embedding_model": False,
		"llm_model": False,
	}

	# vectordb and llm services can be deployed independently
	if value_of(args.vector_db) is None and value_of(args.llm_model) is None:
		raise AssertionError(
			'Error: At least one of "vector_db" or "llm_model" should be provided'
		)

	if value_of(args.vector_db) is not None:
		# embedding model is required for now
		if value_of(args.embedding_model) is None:
			raise AssertionError(
				'Error: "embedding_model" is required if "vector_db" is provided'
			)

		services["vector_db"] = True
		services["embedding_model"] = True

	if value_of(args.llm_model) is not None:
		services["llm_model"] = True

	_create_server(services, args)

