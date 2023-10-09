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

	Args:
		services (dict): A dictionary containing the services to be deployed.
		args (ArgumentParser): An ArgumentParser object containing the command line arguments.

	Raises:
		AssertionError: If at least one of "vector_db" or "llm_model" is not provided.
		AssertionError: If "embedding_model" or "embedding_model_path" is not provided when "vector_db"
										is provided.
		AssertionError: If "llm_model_path" is not provided when "llm_model" is provided.
	"""
	if services["vector_db"]:
		from vectordb import init_db
		from models import init_model

		# TODO: init embedding model from models
		client = init_db(args.vector_db)
		app.config["VECTORDB"] = client

		embedding_model = init_model("embedding", args.embedding_model, args.embedding_model_path)
		app.config["EMBEDDING_MODEL"] = embedding_model

	if services["llm_model"]:
		from models import init_model

		model = init_model("llm", args.llm_model, args.llm_model_path)
		app.config["LLM_MODEL"] = model

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
		"-ep",
		"--embedding_model_path",
		type=str,
		help="Path lookup is made relative to the inside the respective model dir in models dir.",
		metavar="PATH",
	)
	parser.add_argument(
		"-lm",
		"--llm_model",
		type=str,
		choices=models["llm"],
		help="The LLM model to use."
	)
	parser.add_argument(
		"-lp",
		"--llm_model_path",
		type=str,
		help="Path lookup is made from relative the inside the respective model dir in models dir.",
		metavar="PATH",
	)

	args = parser.parse_args()

	services = {
		"vector_db": False,
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

		if value_of(args.embedding_model_path) is None:
			raise AssertionError(
				'Error: "embedding_model_path" is required if "vector_db" is provided'
			)

		services["vector_db"] = True

	if value_of(args.llm_model) is not None:
		if value_of(args.llm_model_path) is None:
			raise AssertionError(
				'Error: "llm_model_path" is required if "llm_model" is provided'
			)

		services["llm_model"] = True

	_create_server(services, args)

