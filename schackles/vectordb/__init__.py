from importlib import import_module

from .base import BaseVectorDB

vector_dbs = ["weaviate"]

__all__ = ["get_vector_db", "vector_dbs", "BaseVectorDB"]


def get_vector_db(vector_db: str) -> BaseVectorDB:
	"""
	Returns the VectorDB client object for the given vector_db

	Args
	----
	vector_db: str
		Name of the vector_db to use

	Returns
	-------
	BaseVectorDB
		Client object for the VectorDB
	"""
	if vector_db not in vector_dbs:
		raise AssertionError(f"Error: vector_db should be one of {vector_dbs}")

	module = import_module(f".{vector_db}", "schackles.vectordb")

	if module is None or not hasattr(module, "VectorDB"):
		raise AssertionError(f"Error: could not load {vector_db}")

	klass = module.VectorDB

	if klass is None or not hasattr(klass, "client"):
		raise AssertionError(
			f"Error: invalid vectordb class for {vector_db}! Check if the file is correct."
		)

	return klass
