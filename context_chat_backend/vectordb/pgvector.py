import typing
from logging import error as log_error

import sqlalchemy as sa
from dotenv import load_dotenv
from langchain.vectorstores import VectorStore
from langchain_core.embeddings import Embeddings
from langchain_postgres import PGVector

from . import get_collection_name, get_user_id_from_collection
from .base import BaseVectorDB, DbException, MetadataFilter, TSearchDict

load_dotenv()


class VectorDB(BaseVectorDB):
	def __init__(self, embedding: Embeddings | None = None, **kwargs):
		if not embedding:
			raise DbException('Error: embedding model not provided for pgvector')
		if 'connection' not in kwargs:
			raise DbException('Error: connection string not provided for pgvector')

		self.client_kwargs = kwargs
		self.embedding = embedding

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
		assert len(filters) > 0

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

		# # validate the filter
		# if metadata_key not in ('source', 'provider'):
		# 	# programmer error
		# 	raise DbException('Error: Invalid metadata key, deletion is only supported for source and provider keys')
		# if not all([re.match(r'^[A-Za-z0-9_]__[A-Za-z0-9_](: [A-Za-z0-9]+)?$', v) for v in values]):
		# 	raise DbException('Error: Invalid metadata values, expected a list of source ids')

		metadata_filter = self.get_metadata_filter([{
			'metadata_key': metadata_key,
			'values': values,
		}])
		if metadata_filter is None:
			raise DbException('Error: PGVector metadata filter error')

		def format_string_value(v):
			return f'\'"{v}"\''

		client = PGVector(self.embedding, collection_name=get_collection_name(user_id), **self.client_kwargs)
		with client._make_sync_session() as session:
			collection = client.get_collection(session)
			filter_by = [
				client.EmbeddingStore.collection_id == collection.uuid,
				# client._create_filter_clause(metadata_filter),
			]

			stmt = (
					sa.delete(
							client.EmbeddingStore,
					)
					.filter(*filter_by)
					.filter(
						# *[client.EmbeddingStore.cmetadata[metadata_key].astext == v for v in values],
						client.EmbeddingStore.cmetadata[metadata_key].in_([sa.cast(f'"{v}"', JSONB) for v in values]),
					)
			)
			# print(stmt.compile(
			# 	dialect=sa.dialects.postgresql.dialect(),
			# 	compile_kwargs={'literal_binds': True},
			# ), flush=True)

			result = session.execute(stmt).fetchall()




		# with client._make_sync_session() as session:
		# 	emb_table_name = client.EmbeddingStore.__tablename__
		# 	collection_uuid = client.get_collection(session).uuid
		# 	conn = session.connection()
		# 	result = conn.execute(sa.text(
		# 		f'''delete from {emb_table_name}
		# 		where
		# 			{emb_table_name}.collection_id = '{collection_uuid}'
		# 			and {emb_table_name}.cmetadata::jsonb->'{metadata_key}' in ({','.join([format_string_value(v) for v in values])})
		# 		returning {emb_table_name}.id, {emb_table_name}.cmetadata'''
		# 	), {
		# 		'collection_uuid': collection_uuid,
		# 		'values': values,
		# 	}).fetchall()

			if result is None:
				return False

			if len(result) < len(values):
				log_error('Some sources were not deleted.\nRequested:%s\nDeleted:%s',
					values,
					{r[1]['source'] for r in result},
				)

		return True


class JSONB(sa.sql.sqltypes.Indexable, sa.sql.sqltypes.TypeEngine[typing.Any]):
    __visit_name__ = "JSONB"

    hashable = False
