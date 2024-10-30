import os
from logging import error as log_error
from typing import Any

import sqlalchemy as sa
from dotenv import load_dotenv
from langchain.vectorstores import VectorStore
from langchain_core.embeddings import Embeddings
from langchain_postgres import PGVector

from . import get_collection_name, get_user_id_from_collection
from .base import BaseVectorDB, DbException, MetadataFilter, TSearchDict

load_dotenv()


class JSONB(sa.sql.sqltypes.Indexable, sa.sql.sqltypes.TypeEngine[Any]):  # pyright: ignore[reportAttributeAccessIssue]
	__visit_name__ = "JSONB"

	hashable = False


class VectorDB(BaseVectorDB):
	def __init__(self, embedding: Embeddings | None = None, **kwargs):
		if not embedding:
			raise DbException('Error: embedding model not provided for pgvector')
		if os.getenv('CCB_DB_URL') is None and 'connection' not in kwargs:
			raise DbException(
				'Error: Either env var CCB_DB_URL or connection string in the config is required for pgvector'
			)

		self.embedding = embedding
		self.client_kwargs = kwargs
		# Use connection string from env var if not provided in kwargs
		self.client_kwargs.update({'connection': str(self.client_kwargs.get('connection', os.environ['CCB_DB_URL']))})
		# todo
		self.client_kwargs.update({'connection': 'postgresql+psycopg://ccbuser:ccbpass@localhost:5432/ccb'})
		print('client kwargs:', self.client_kwargs)
		print(f'Using connection string: {self.client_kwargs["connection"]}')
		print('Type of connection string:', type(self.client_kwargs['connection']))
		engine = sa.create_engine(self.client_kwargs['connection'])
		with engine.connect() as conn:
			result = conn.execute(sa.text('select pg_catalog.version()')).fetchall()
			print(result, flush=True)

	def get_users(self) -> list[str]:
		engine = sa.create_engine(self.client_kwargs['connection'])
		with engine.connect() as conn:
			result = conn.execute(sa.text('select name from langchain_pg_collection')).fetchall()
			return [get_user_id_from_collection(r[0]) for r in result]

	def setup_schema(self, user_id: str) -> None:
		...

	def get_user_client(
		self,
		user_id: str,
		embedding: Embeddings | None = None  # Use this embedding if not None or use global embedding
	) -> VectorStore:
		# todo: get rid of embedding param here and make it not None in __init__
		emb = self.embedding or embedding
		if not emb:
			raise DbException('Error: embedding model not provided for pgvector')

		return PGVector(emb, collection_name=get_collection_name(user_id), **self.client_kwargs)

	def get_metadata_filter(self, filters: list[MetadataFilter]) -> dict | None:
		if len(filters) == 0:
			raise DbException('Error: PGVector metadata filter received empty filters')

		try:
			if len(filters) == 1:
				return { filters[0]['metadata_key']: { '$in': filters[0]['values'] } }

			return {
				'$or': [{
					f['metadata_key']: { '$in': f['values'] }
				} for f in filters]
			}
		except (KeyError, IndexError) as e:
			log_error(e)
			return None

	def get_objects_from_metadata(
		self,
		user_id: str,
		metadata_key: str,
		values: list[str],
	) -> TSearchDict:
		data_filter = self.get_metadata_filter([{
			'metadata_key': metadata_key,
			'values': values,
		}])

		if data_filter is None:
			raise DbException('Error: PGVector metadata filter error')

		try:
			client = PGVector(self.embedding, collection_name=get_collection_name(user_id), **self.client_kwargs)
			with client._make_sync_session() as session:
				collection = client.get_collection(session)
				filter_by = [
					client.EmbeddingStore.collection_id == collection.uuid,
					client._create_filter_clause(data_filter)
				]
				stmt = (
						sa.select(
								client.EmbeddingStore.id,
								client.EmbeddingStore.cmetadata,
						)
						.filter(*filter_by)
				)

				results = session.execute(stmt).fetchall()

			if len(results) == 0:
				return {}
		except Exception as e:
			raise DbException('Error: PGVector query error') from e

		try:
			output = {}
			for r in results:
				meta = r.cmetadata
				output[meta[metadata_key]] = {
					'id': r.id,
					'modified': meta['modified'],
				}
		except (KeyError, IndexError) as e:
			raise DbException('Error: PGVector metadata parsing error') from e

		return output

	def delete(self, user_id: str, metadata_key: str, values: list[str]) -> bool:
		if len(values) == 0:
			return True

		metadata_filter = self.get_metadata_filter([{
			'metadata_key': metadata_key,
			'values': values,
		}])
		if metadata_filter is None:
			raise DbException('Error: PGVector metadata filter error')

		client = PGVector(self.embedding, collection_name=get_collection_name(user_id), **self.client_kwargs)
		with client._make_sync_session() as session:
			collection = client.get_collection(session)

			stmt = (
				sa.delete(
					client.EmbeddingStore,
				)
				.filter(client.EmbeddingStore.collection_id == collection.uuid)
				.filter(client.EmbeddingStore.cmetadata[metadata_key].in_([sa.cast(f'"{v}"', JSONB) for v in values]))
			)

			result = session.execute(stmt)
			session.commit()

			if result.rowcount == 0:
				return False

		return True
