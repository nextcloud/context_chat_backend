from logging import error as log_error
from os import getenv
from typing import List, Optional

from dotenv import load_dotenv
from langchain.schema.embeddings import Embeddings
from langchain.vectorstores import VectorStore, Chroma
from chromadb.config import Settings
from chromadb import Client

from .base import BaseVectorDB
from ..utils import COLLECTION_NAME

load_dotenv()


class VectorDB(BaseVectorDB):
	def __init__(self, embedding: Optional[Embeddings] = None, **kwargs):
		try:
			client = Client(Settings(
				anonymized_telemetry=False,
				**{
					'is_persistent': True,
					'persist_directory': getenv('VECTORDB_DIR', './vector_db_data'),
					**kwargs,
				},
			))
		except Exception as e:
			raise Exception(f'Error: Chromadb instantiation error: {e}')

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
			embedding: Optional[Embeddings] = None  # Use this embedding if not None or use global embedding
		) -> Optional[VectorStore]:
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
		values: List[str],
		contains: bool = False,
	) -> dict:
		# NOTE: the limit of objects returned is not known, maybe it would be better to set one manually

		if not self.client:
			raise Exception('Error: Chromadb client not initialised')

		self.setup_schema(user_id)

		if len(values) == 0:
			return {}

		if len(values) == 1:
			if contains:
				data_filter = { metadata_key: { '$in': values[0] } }
			else:
				data_filter = { metadata_key: values[0] }
		else:
			if contains:
				data_filter = {'$or': [{ metadata_key: { '$in': val } } for val in values]}
			else:
				data_filter = {'$or': [{ metadata_key: val } for val in values]}

		try:
			results = self.client.get_collection(COLLECTION_NAME(user_id)).get(
				where=data_filter,
				include=['metadatas']
			)
		except Exception as e:
			log_error(f'Error: Chromadb query error: {e}')
			return {}

		if len(results.get('ids')) == 0:
			return {}

		output = {}
		try:
			for i, _id in enumerate(results.get('ids')):
				meta = results['metadatas'][i]
				output[meta[metadata_key]] = {
					'id': _id,
					'modified': meta['modified'],
				}
		except Exception as e:
			log_error(f'Error: Chromadb query key error: {e}')
			return {}

		return output
