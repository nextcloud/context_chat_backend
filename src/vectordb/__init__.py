from utils import local_dynamic_import
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

	module_name = vector_db + "_local"
	file_path = f"src/vectordb/{vector_db}.py"
	module = local_dynamic_import(module_name, file_path)

	if module is None or hasattr(module, "VectorDB") is False:
		raise AssertionError(f"Error: could not load {vector_db}")

	klass = module.VectorDB
	return klass
