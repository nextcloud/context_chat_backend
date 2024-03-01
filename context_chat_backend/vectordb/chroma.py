from logging import error as log_error
from os import getenv

from chromadb import Client
from chromadb.config import Settings
from dotenv import load_dotenv
from langchain.schema.embeddings import Embeddings
from langchain.vectorstores import Chroma, VectorStore

from . import COLLECTION_NAME, USER_ID_FROM_COLLECTION
from .base import BaseVectorDB, MetadataFilter, TSearchDict

load_dotenv()


class VectorDB(BaseVectorDB):
	def __init__(self, embedding: Embeddings | None = None, **kwargs):
		try:
			client = Client(Settings(
				anonymized_telemetry=False,
				**{
					'is_persistent': True,
					'persist_directory': getenv('VECTORDB_DIR', './persistent_storage/vector_db_data'),
					**kwargs,
				},
			))
		except Exception as e:
			raise Exception('Error: Chromadb instantiation error') from e

		if client.heartbeat() <= 0:
			raise Exception('Error: Chromadb connection error')

		self.client = client
		self.embedding = embedding

	def get_users(self) -> list[str]:
		if not self.client:
			raise Exception('Error: Chromadb client not initialised')

		return [USER_ID_FROM_COLLECTION(collection.name) for collection in self.client.list_collections()]

	def setup_schema(self, user_id: str) -> None:
		if not self.client:
			raise Exception('Error: Chromadb client not initialised')

		# dynamic schema
		self.client.get_or_create_collection(COLLECTION_NAME(user_id))

	def get_user_client(
			self,
			user_id: str,
			embedding: Embeddings | None = None  # Use this embedding if not None or use global embedding
		) -> VectorStore | None:
		self.setup_schema(user_id)

		em = None
		if self.embedding is not None:
			em = self.embedding
		elif embedding is not None:
			em = embedding

		return Chroma(
			client=self.client,
			collection_name=COLLECTION_NAME(user_id),
			embedding_function=em,
		)

	def get_metadata_filter(self, filters: list[MetadataFilter]) -> dict | None:
		if len(filters) == 0:
			return None

		if len(filters) == 1:
			return { filters[0]['metadata_key']: { '$in': filters[0]['values'] } }

		return {
			'$or': [{
				f['metadata_key']: { '$in': f['values'] }
			} for f in filters]
		}

	def get_objects_from_metadata(
		self,
		user_id: str,
		metadata_key: str,
		values: list[str],
	) -> TSearchDict:
		# NOTE: the limit of objects returned is not known, maybe it would be better to set one manually

		if not self.client:
			raise Exception('Error: Chromadb client not initialised')

		self.setup_schema(user_id)

		try:
			data_filter = self.get_metadata_filter([{
				'metadata_key': metadata_key,
				'values': values,
			}])
		except KeyError as e:
			# todo: info instead of error
			log_error(f'Error: Chromadb filter error: {e}')
			return {}

		if data_filter is None:
			return {}

		try:
			results = self.client.get_collection(COLLECTION_NAME(user_id)).get(
				where=data_filter,
				include=['metadatas']
			)
		except Exception as e:
			log_error(f'Error: Chromadb query error: {e}')
			return {}

		if len(results.get('ids', [])) == 0:
			return {}

		res_metadatas = results.get('metadatas')
		if res_metadatas is None:
			return {}

		output = {}
		try:
			for i, _id in enumerate(results.get('ids')):
				meta = res_metadatas[i]
				output[meta[metadata_key]] = {
					'id': _id,
					'modified': meta['modified'],
				}
		except Exception as e:
			log_error(f'Error: Chromadb query key error: {e}')
			return {}

		return output
