from os import getenv

from dotenv import load_dotenv
from langchain.schema.embeddings import Embeddings
from langchain.vectorstores import VectorStore
from langchain_community.vectorstores.weaviate import Weaviate
from weaviate import AuthApiKey, Client

from ..utils import value_of
from . import get_collection_name, get_user_id_from_collection
from .base import BaseVectorDB, DbException, MetadataFilter, TSearchDict

load_dotenv()

class_schema = {
	'properties': [
		{
			'dataType': ['text'],
			'description': 'The actual text',
			'name': 'text',
		},
		{
			'dataType': ['text'],
			'description': 'The type of source/mimetype of file',
			'name': 'type',
		},
		{
			'dataType': ['text'],
			'description': 'The name or subject of the source',
			'name': 'title',
		},
		{
			'dataType': ['text'],
			'description': 'The source of the text (for files: `files__default: fileId`)',
			'name': 'source',
		},
		{
			'dataType': ['int'],
			'description': 'Start index of chunk',
			'name': 'start_index',
		},
		{
			# https://weaviate.io/developers/weaviate/config-refs/datatypes#datatype-date
			'dataType': ['text'],
			'description': 'Last modified time of the file',
			'name': 'modified',
		},
		{
			'dataType': ['text'],
			'description': 'The provider of the source',
			'name': 'provider',
		}
	],
	# TODO: optimisation for large number of objects
	'vectorIndexType': 'hnsw',
	'vectorIndexConfig': {
		'skip': False,
		# 'ef': 99,
		# 'efConstruction': 127,  # minimise this for faster indexing
		# 'maxConnections': 63,
	}
}


class VectorDB(BaseVectorDB):
	def __init__(self, embedding: Embeddings | None = None, **kwargs):
		try:
			client = Client(
				**{
					**({
						'auth_client_secret': AuthApiKey(getenv('WEAVIATE_APIKEY', '')),
					} if value_of(getenv('WEAVIATE_APIKEY')) is not None else {}),
					'url': getenv('WEAVIATE_URL'),
					'timeout_config': (1, 20),
					**kwargs,
				},
			)
		except Exception as e:
			raise DbException('Error: Weaviate connection error') from e

		if not client.is_ready():
			raise DbException('Error: Weaviate connection error')

		self.client = client
		self.embedding = embedding

	def get_users(self) -> list[str]:
		if not self.client:
			raise DbException('Error: Weaviate client not initialised')

		return [
			get_user_id_from_collection(klass['class'])
			for klass in self.client.schema.get().get('classes', [])
		]

	def setup_schema(self, user_id: str) -> None:
		if not self.client:
			raise DbException('Error: Weaviate client not initialised')

		if self.client.schema.exists(get_collection_name(user_id)):
			return

		self.client.schema.create_class({
			'class': get_collection_name(user_id),
			**class_schema,
		})

	def get_user_client(
			self,
			user_id: str,
			embedding: Embeddings | None = None  # Use this embedding if not None or use global embedding
		) -> VectorStore:
		self.setup_schema(user_id)

		weaviate_obj = Weaviate(
			client=self.client,
			index_name=get_collection_name(user_id),
			text_key='text',
			embedding=(self.embedding or embedding),
			by_text=False,
		)
		weaviate_obj._query_attrs = ['text', 'start_index', 'source', 'title', 'type', 'modified']

		return weaviate_obj

	def get_metadata_filter(self, filters: list[MetadataFilter]) -> dict | None:
		if len(filters) == 0:
			return None

		try:
			if len(filters) == 1:
				return {
					'path': filters[0]['metadata_key'],
					'operator': 'ContainsAny',
					'valueTextList': filters[0]['values'],
				}

			return {
				'operator': 'Or',
				'operands': [{
						'path': f['metadata_key'],
						'operator': 'ContainsAny',
						'valueTextList': f['values'],
					} for f in filters]
			}
		except (KeyError, IndexError):
			return None

	def get_objects_from_metadata(
		self,
		user_id: str,
		metadata_key: str,
		values: list[str],
	) -> TSearchDict:
		# NOTE: the limit of objects returned is not known, maybe it would be better to set one manually

		if not self.client:
			raise DbException('Error: Weaviate client not initialised')

		self.setup_schema(user_id)

		data_filter = self.get_metadata_filter([{
			'metadata_key': metadata_key,
			'values': values,
		}])
		if data_filter is None:
			raise DbException('Error: Weaviate metadata filter error')

		results = self.client.query \
			.get(get_collection_name(user_id), [metadata_key, 'modified']) \
			.with_additional('id') \
			.with_where(data_filter) \
			.do()

		if results.get('errors') is not None:
			raise DbException(f'Error: Weaviate query error: {results.get("errors")}')

		dmeta = {}
		for val in values:
			dmeta[val] = True

		try:
			results = results['data']['Get'][get_collection_name(user_id)]
			output = {}
			for result in results:
				# case sensitive matching
				if dmeta.get(result[metadata_key]) is None:
					continue

				output[result[metadata_key]] = {
					'id': result['_additional']['id'],
					'modified': result['modified'],
				}

			return output
		except (KeyError, IndexError) as e:
			raise DbException('Error: Weaviate metadata parsing error') from e

	def delete(self, user_id: str, metadata_key: str, values: list[str]) -> bool:
		if len(values) == 0:
			return True

		objs = self.get_objects_from_metadata(user_id, metadata_key, values)
		ids = [
			obj.get('id')
			for obj in objs.values()
			if value_of(obj.get('id')) is not None
		]

		return self.delete_by_ids(user_id, ids)
