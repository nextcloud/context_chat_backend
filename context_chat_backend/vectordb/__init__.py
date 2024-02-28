from importlib import import_module

from .base import BaseVectorDB, MetadataFilter

vector_dbs = ['weaviate', 'chroma']

__all__ = ['get_vector_db', 'vector_dbs', 'BaseVectorDB', 'COLLECTION_NAME', 'MetadataFilter']


# class name/index name is capitalized (user1 => User1) maybe because it is a class name,
# so the solution is to use Vector_user1 instead of user1
COLLECTION_NAME = lambda user_id: f'Vector_{user_id}'


def get_vector_db(db_name: str) -> BaseVectorDB:
	'''
	Returns the VectorDB client object for the given vector_db

	Args
	----
	db_name: str
		Name of the vector_db to use

	Returns
	-------
	BaseVectorDB
		Client object for the VectorDB
	'''
	if db_name not in vector_dbs:
		raise AssertionError(f'Error: vector_db should be one of {vector_dbs}')

	module = import_module(f'.{db_name}', 'context_chat_backend.vectordb')

	if module is None or not hasattr(module, 'VectorDB'):
		raise AssertionError(f'Error: could not load {db_name}')

	klass = module.VectorDB

	if klass is None or not hasattr(klass, 'client'):
		raise AssertionError(
			f'Error: invalid vectordb class for {db_name}! Check if the file is correct.'
		)

	return klass
