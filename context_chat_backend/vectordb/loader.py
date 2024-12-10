from importlib import import_module

from .base import BaseVectorDB

vector_dbs = ['pgvector']

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

	:raises AssertionError:
		if the db_name is not in vector_dbs
		if the db_name does not have a valid VectorDB class
		if the VectorDB class does not have a client attribute
	:raises ImportError:
		if the module could not be imported
	'''
	if db_name not in vector_dbs:
		raise AssertionError(f'Error: vector_db should be one of {vector_dbs}')

	try:
		module = import_module(f'.{db_name}', 'context_chat_backend.vectordb')
	except Exception as e:
		# catch all exceptions as ImportError
		raise ImportError(f'Error: could not import {db_name}') from e

	if module is None or not hasattr(module, 'VectorDB'):
		raise AssertionError(f'Error: invalid vectordb module for {db_name}! "VectorDB" class not found.')

	klass = module.VectorDB

	if klass is None or not hasattr(klass, 'client'):
		raise AssertionError(
			f'Error: invalid vectordb class for {db_name}! "client" attribute not found in "VectorDB" class.'
		)

	return klass
