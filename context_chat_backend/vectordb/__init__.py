import re
from importlib import import_module

from .base import BaseVectorDB, MetadataFilter

vector_dbs = ['weaviate', 'chroma']

__all__ = [
	'BaseVectorDB',
	'MetadataFilter',
	'get_collection_name',
	'get_user_id_from_collection',
	'get_vector_db',
	'vector_dbs',
]


# transitory cache for user_id to collection name
user_id_cache = {}

re_user_id = re.compile(r'^[a-zA-Z0-9_.\-@ ]{1,56}$')
# class name/index name is capitalized (user1 => User1) maybe because it is a class name,
# so the solution is to use Vector_user1 instead of user1
def get_collection_name(user_id: str) -> str:
	if user_id in user_id_cache:
		return user_id_cache[user_id]

	if not re_user_id.match(user_id):
		raise AssertionError('Error: invalid user_id format, should consist of alphanumeric characters, hyphen, underscore, dot, and space only. Length should not exceed 56 characters.')  # noqa: E501

	# should not end in a special character
	if user_id[-1] in '_.-@ ':
		raise AssertionError('Error: user_id should not end in a special character.')

	# replace space with double underscore
	user_id = user_id.replace(' ', '__')
	# replace consecutive dots with .n. (n is the number of dots)
	user_id = re.sub(r'\.{2,}', lambda m: f'.{len(m.group())}.', user_id)
	# replace @ with .at.
	user_id = user_id.replace('@', '.at.')

	# recheck length constraints
	if len(user_id) > 56:
		raise AssertionError(f'Error: length of cleaned up user_id should not exceed 56 characters, processed username: {user_id}.')  # noqa: E501

	collection_name = f'Vector_{user_id}'
	user_id_cache[user_id] = collection_name

	return collection_name


def get_user_id_from_collection(collection_name: str) -> str:
	return collection_name[7:]


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
