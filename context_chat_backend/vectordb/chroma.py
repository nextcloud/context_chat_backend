from os import getenv

from chromadb import Client
from chromadb.config import Settings
from dotenv import load_dotenv
from langchain.schema.embeddings import Embeddings
from langchain.vectorstores import VectorStore
from langchain_community.vectorstores.chroma import Chroma

from . import get_collection_name, get_user_id_from_collection
from .base import BaseVectorDB, DbException, MetadataFilter, TSearchDict

load_dotenv()


class VectorDB(BaseVectorDB):
	def __init__(self, embedding: Embeddings | None = None, **kwargs):
		try:
			client = Client(Settings(
				anonymized_telemetry=False,
				**{
					'is_persistent': True,
					'persist_directory': getenv('VECTORDB_DIR', 'persistent_storage/vector_db_data'),
					**kwargs,
				},
			))
		except Exception as e:
			raise DbException('Error: Chromadb instantiation error') from e

		if client.heartbeat() <= 0:
			raise DbException('Error: Chromadb connection error')

		self.client = client
		self.embedding = embedding

	def get_users(self) -> list[str]:
		if not self.client:
			raise DbException('Error: Chromadb client not initialised')

		return [get_user_id_from_collection(collection.name) for collection in self.client.list_collections()]

	def setup_schema(self, user_id: str) -> None:
		if not self.client:
			raise DbException('Error: Chromadb client not initialised')

		# dynamic schema
		self.client.get_or_create_collection(get_collection_name(user_id))

	def get_user_client(
			self,
			user_id: str,
			embedding: Embeddings | None = None  # Use this embedding if not None or use global embedding
		) -> VectorStore:
		self.setup_schema(user_id)

		return Chroma(
			client=self.client,
			collection_name=get_collection_name(user_id),
			embedding_function=(self.embedding or embedding),
		)

	def get_metadata_filter(self, filters: list[MetadataFilter]) -> dict | None:
		if len(filters) == 0:
			return None

		try:
			if len(filters) == 1:
				return { filters[0]['metadata_key']: { '$in': filters[0]['values'] } }

			return {
				'$or': [{
					f['metadata_key']: { '$in': f['values'] }
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
			raise DbException('Error: Chromadb client not initialised')

		self.setup_schema(user_id)

		data_filter = self.get_metadata_filter([{
			'metadata_key': metadata_key,
			'values': values,
		}])

		if data_filter is None:
			# todo: exception handling and Exception docs update
			raise DbException('Error: Chromadb metadata filter error')

		try:
			results = self.client.get_collection(get_collection_name(user_id)).get(
				where=data_filter,
				include=['metadatas']
			)

			if len(results.get('ids', [])) == 0:
				return {}
		except Exception as e:
			# todo: exception handling
			raise DbException('Error: Chromadb query error') from e

		try:
			output = {}
			for i, _id in enumerate(results.get('ids')):
				meta = results['metadatas'][i]
				output[meta[metadata_key]] = {
					'id': _id,
					'modified': meta['modified'],
				}
		except (KeyError, IndexError) as e:
			# todo: exception handling
			raise DbException('Error: Chromadb metadata parsing error') from e

		return output
