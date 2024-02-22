from logging import error as log_error
from os import getenv

from chromadb import Client, Where
from chromadb.config import Settings
from dotenv import load_dotenv
from langchain.schema.embeddings import Embeddings
from langchain.vectorstores import Chroma, VectorStore

from . import COLLECTION_NAME
from .base import BaseVectorDB, TSearchDict

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

		if len(values) == 0:
			return {}

		data_filter: Where = { metadata_key: { '$in': values } }  # type: ignore

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
