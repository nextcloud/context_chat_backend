#
# SPDX-FileCopyrightText: 2024 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
import logging
import os
from datetime import datetime

import sqlalchemy as sa
import sqlalchemy.orm as orm
from dotenv import load_dotenv
from fastapi import UploadFile
from langchain.schema import Document
from langchain.vectorstores import VectorStore
from langchain_core.embeddings import Embeddings
from langchain_postgres.vectorstores import Base, PGVector

from ..chain.types import InDocument, ScopeType
from ..utils import timed
from .base import BaseVectorDB
from .types import DbException, SafeDbException, UpdateAccessOp

load_dotenv()

COLLECTION_NAME = 'ccb_store'
DOCUMENTS_TABLE_NAME = 'docs'
ACCESS_LIST_TABLE_NAME = 'access_list'

logger = logging.getLogger('ccb.vectordb')

# we're responsible for keeping this in sync with the langchain_postgres table
class DocumentsStore(Base):
	"""Documents table that links to chunks."""

	__tablename__ = DOCUMENTS_TABLE_NAME

	source_id: orm.Mapped[str] = orm.mapped_column(nullable=False, primary_key=True, index=True)
	provider: orm.Mapped[str] = orm.mapped_column(nullable=False)
	# complete id including the provider
	modified: orm.Mapped[datetime] = orm.mapped_column(
		sa.DateTime,
		server_default=sa.func.now(),
		nullable=False,
	)
	chunks: orm.Mapped[list[sa.UUID]] = orm.mapped_column(
		sa.ARRAY(sa.UUID(as_uuid=True)),
		nullable=False,
	)

	__table_args__ = (
		sa.Index(
			'provider_idx',
			'provider',
		),
		sa.Index(
			'source_id_modified_idx',
			'source_id',
			'modified',
			unique=True,
		),
	)


class AccessListStore(Base):
	"""User access list."""

	__tablename__ = ACCESS_LIST_TABLE_NAME

	id: orm.Mapped[int] = orm.mapped_column(primary_key=True, autoincrement=True)

	uid: orm.Mapped[str] = orm.mapped_column(nullable=False)
	source_id: orm.Mapped[str] = orm.mapped_column(
		sa.ForeignKey(
			# NOTE: lookout for changes in this table name or generally in langchain_postgres
			f'{DOCUMENTS_TABLE_NAME}.source_id',
			ondelete='CASCADE',
		),
	)

	__table_args__ = (
		sa.Index(
			'uid_chunk_id_idx',
			'uid',
			'source_id',
			unique=True,
		),
	)

	@classmethod
	def get_all(cls, session: sa.orm.Session) -> list[str]:
		try:
			return [r.uid for r in session.query(cls.uid).distinct().all()]
		except Exception as e:
			raise DbException('Error: getting all users from access list') from e


class VectorDB(BaseVectorDB):
	def __init__(self, embedding: Embeddings | None = None, **kwargs):
		if not embedding:
			raise DbException('Error: embedding model not provided for pgvector')
		if os.getenv('CCB_DB_URL') is None and 'connection' not in kwargs:
			raise DbException(
				'Error: Either env var CCB_DB_URL or connection string in the config is required for pgvector'
			)

		# Use connection string from env var if not provided in kwargs
		if 'connection' not in kwargs:
			kwargs['connection'] = os.environ['CCB_DB_URL']

		# setup langchain db + our access list table
		self.client = PGVector(embedding, collection_name=COLLECTION_NAME, **kwargs)

	def get_instance(self) -> VectorStore:
		return self.client

	def session_maker(self) -> orm.Session:
		try:
			return self.client.session_maker()
		except Exception as e:
			raise DbException('Error: creating session for vectordb') from e

	def get_users(self) -> list[str]:
		with self.session_maker() as session:
			try:
				return AccessListStore.get_all(session)
			except Exception as e:
				raise DbException('Error: getting a list of all users from access list') from e

	def add_indocuments(self, indocuments: list[InDocument]) -> list[str]:
		added_sources = []

		with self.session_maker() as session:
			for indoc in indocuments:
				try:
					chunk_ids = self.client.add_documents(indoc.documents)

					doc = DocumentsStore(
						source_id=indoc.source_id,
						provider=indoc.provider,
						modified=datetime.fromtimestamp(indoc.modified),
						chunks=chunk_ids,
					)
					session.add(doc)
					session.commit()

					self.decl_update_access(indoc.userIds, indoc.source_id, session)
					added_sources.append(indoc.source_id)
				except SafeDbException as e:
					logger.debug('Error adding documents to vectordb', exc_info=e, extra={
						'source_id': indoc.source_id,
					})
					continue
				except Exception as e:
					logger.exception('Error adding documents to vectordb', exc_info=e, extra={
						'source_id': indoc.source_id,
					})
					continue

		return added_sources

	@timed
	def check_sources(self, sources: list[UploadFile]) -> tuple[list[str], list[str]]:
		with self.session_maker() as session:
			try:
				stmt = (
					sa.select(DocumentsStore.source_id)
					.filter(DocumentsStore.source_id.in_([source.filename for source in sources]))
					.with_for_update()
				)

				results = session.execute(stmt).fetchall()
				existing_sources = {r.source_id for r in results}
				to_embed = [source.filename for source in sources if source.filename not in existing_sources]

				to_delete = []

				for source in sources:
					stmt = (
						sa.select(DocumentsStore.source_id)
						.filter(DocumentsStore.source_id == source.filename)
						.filter(DocumentsStore.modified < sa.cast(
							datetime.fromtimestamp(int(source.headers['modified'])),
							sa.DateTime,
						))
					)

					result = session.execute(stmt).fetchone()
					if result is not None:
						to_embed.append(result.source_id)
						to_delete.append(result.source_id)

				if len(to_delete) > 0:
					self.delete_source_ids(to_delete, session)

			except Exception as e:
				session.rollback()
				raise DbException('Error: checking sources in vectordb') from e

			still_existing_sources = [
				source
				for source in existing_sources
				if source not in to_delete
			]

			# the pyright issue stems from source.filename, which has already been validated
			return list(still_existing_sources), to_embed  # pyright: ignore[reportReturnType]

	def decl_update_access(self, user_ids: list[str], source_id: str, session_: orm.Session | None = None):
		session = session_ or self.session_maker()

		try:
			# check if source_id exists
			stmt = (
				sa.select(DocumentsStore.source_id)
				.filter(DocumentsStore.source_id == source_id)
			)
			result = session.execute(stmt).fetchone()
			if result is None:
				raise SafeDbException(
					'Error: source id not found. It is possible that this document is still in the index queue'
					' and has not been added to the database yet.'
					' This is generally not an error and will resolve itself when the document is indexed.',
					404,
				)

			stmt = (
				sa.delete(AccessListStore)
				.filter(AccessListStore.source_id == source_id)
			)
			session.execute(stmt)
			session.commit()

			stmt = (
				sa.dialects.postgresql.insert(AccessListStore)
				.values([
					{
						'uid': user_id,
						'source_id': source_id,
					}
					for user_id in user_ids
				])
				.on_conflict_do_nothing(index_elements=['uid', 'source_id'])
			)
			session.execute(stmt)
			session.commit()
		except SafeDbException as e:
			session.rollback()
			raise e
		except Exception as e:
			session.rollback()
			raise DbException('Error: updating access list') from e
		finally:
			if session_ is None:
				session.close()

	def update_access(
		self,
		op: UpdateAccessOp,
		user_ids: list[str],
		source_id: str,
		session_: orm.Session | None = None,
	):
		session = session_ or self.session_maker()

		try:
			# check if source_id exists
			stmt = (
				sa.select(DocumentsStore.source_id)
				.filter(DocumentsStore.source_id == source_id)
			)
			result = session.execute(stmt).fetchone()
			if result is None:
				if session_ is None:
					session.close()
				raise SafeDbException('Error: source id not found', 404)

			match op:
				case UpdateAccessOp.allow:
					stmt = (
						sa.dialects.postgresql.insert(AccessListStore)
						.values([
							{
								'uid': user_id,
								'source_id': source_id,
							}
							for user_id in user_ids
						])
						.on_conflict_do_nothing(index_elements=['uid', 'source_id'])
					)
					session.execute(stmt)
					session.commit()

				case UpdateAccessOp.deny:
					stmt = (
						sa.delete(AccessListStore)
						.filter(AccessListStore.uid.in_(user_ids))
						.filter(AccessListStore.source_id == source_id)
					)
					session.execute(stmt)
					session.commit()

					# check if all entries related to the source were deleted
					self._cleanup_if_orphaned([source_id], session)
				case _:
					if session_ is None:
						session.close()
					raise SafeDbException('Error: invalid access operation', 400)
		except SafeDbException as e:
			session.rollback()
			raise e
		except Exception as e:
			session.rollback()
			raise DbException('Error: updating access list') from e
		finally:
			if session_ is None:
				session.close()

	def update_access_provider(
		self,
		op: UpdateAccessOp,
		user_ids: list[str],
		provider_id: str,
	):
		with self.session_maker() as session:
			try:
				stmt = (
					sa.select(DocumentsStore.source_id)
					.filter(DocumentsStore.provider == provider_id)
				)
				result = session.execute(stmt).fetchall()
				source_ids = [str(r.source_id) for r in result]
			except Exception as e:
				raise DbException('Error: getting source ids for provider') from e

			# painful process
			for source_id in source_ids:
				self.update_access(op, user_ids, source_id, session)

	def _cleanup_if_orphaned(self, source_ids: list[str], session_: orm.Session | None = None):
		if len(source_ids) == 0:
			return

		filter_ = [
			AccessListStore.source_id.in_(source_ids) if len(source_ids) > 1
			else AccessListStore.source_id == source_ids[0]
		]

		session = session_ or self.session_maker()

		try:
			stmt = (
				sa.select(AccessListStore.source_id)
				.filter(*filter_)
				.distinct()
			)
			result = session.execute(stmt).fetchall()
		except Exception as e:
			if session_ is None:
				session.close()
			raise DbException('Error: getting source ids from access list') from e

		existing_links = [str(r.source_id) for r in result]
		to_delete = [source_id for source_id in source_ids if source_id not in existing_links]

		if len(to_delete) > 0:
			self.delete_source_ids(to_delete, session_)

		if session_ is None:
			session.close()

	def delete_source_ids(self, source_ids: list[str], session_: orm.Session | None = None):
		session = session_ or self.session_maker()

		try:
			collection = self.client.get_collection(session)

			# entry from "AccessListStore" is deleted automatically due to the foreign key constraint
			stmt_doc = (
				sa.delete(DocumentsStore)
				.filter(DocumentsStore.source_id.in_(source_ids))
				.returning(DocumentsStore.chunks)
			)

			doc_result = session.execute(stmt_doc)
			chunks_to_delete = [str(c) for res in doc_result for c in res.chunks]
		except Exception as e:
			session.rollback()
			if session_ is None:
				session.close()
			raise DbException('Error: deleting source ids from docs store') from e

		try:
			stmt_chunks = (
				sa.delete(self.client.EmbeddingStore)
				.filter(self.client.EmbeddingStore.collection_id == collection.uuid)
				.filter(self.client.EmbeddingStore.id.in_(chunks_to_delete))
			)

			session.execute(stmt_chunks)
			session.commit()
		except Exception as e:
			logger.error('Error deleting chunks, rolling back documents store deletion for source ids')
			session.rollback()
			raise DbException(
				'Error: deleting chunks, rolling back documents store deletion for source ids'
			) from e
		finally:
			if session_ is None:
				session.close()

	def delete_provider(self, provider_key: str):
		with self.session_maker() as session:
			try:
				collection = self.client.get_collection(session)

				stmt = (
					sa.delete(DocumentsStore)
					.filter(DocumentsStore.provider == provider_key)
					.returning(DocumentsStore.chunks)
				)

				doc_result = session.execute(stmt)
				chunks_to_delete = [str(c) for res in doc_result for c in res.chunks]
			except Exception as e:
				session.rollback()
				raise DbException('Error: deleting provider from docs store') from e

			try:
				stmt = (
					sa.delete(self.client.EmbeddingStore)
					.filter(self.client.EmbeddingStore.collection_id == collection.uuid)
					.filter(self.client.EmbeddingStore.id.in_(chunks_to_delete))
				)
				session.execute(stmt)
				session.commit()
			except Exception as e:
				session.rollback()
				raise DbException(
					'Error: deleting chunks, rolling back documents store deletion for provider'
				) from e

	def delete_user(self, user_id: str):
		with self.session_maker() as session:
			try:
				stmt = (
					sa.delete(AccessListStore)
					.filter(AccessListStore.uid == user_id)
					.returning(AccessListStore.source_id)
				)

				result = session.execute(stmt)
				source_ids = {str(r.source_id) for r in result}
			except Exception as e:
				session.rollback()
				raise DbException('Error: deleting user from access list') from e

			self._cleanup_if_orphaned(list(source_ids), session)

	@timed
	def doc_search(
		self,
		user_id: str,
		query: str,
		k: int,
		scope_type: ScopeType | None = None,
		scope_list: list[str] | None = None,
	) -> list[Document]:
		if scope_type is not None and scope_list is None:
			raise SafeDbException('Error: scope_list is required when scope_type is provided', 400)

		try:
			with self.session_maker() as session:
				# get user's access list
				stmt = (
					sa.select(AccessListStore.source_id)
					.filter(AccessListStore.uid == user_id)
				)
				result = session.execute(stmt).fetchall()
				source_ids = [r.source_id for r in result]

				doc_filters = [DocumentsStore.source_id.in_(source_ids)]
				match scope_type:
					case ScopeType.PROVIDER:
						doc_filters.append(DocumentsStore.provider.in_(scope_list))  # pyright: ignore[reportArgumentType]
					case ScopeType.SOURCE:
						doc_filters.append(DocumentsStore.source_id.in_(scope_list))  # pyright: ignore[reportArgumentType]

				# get chunks associated with the source_ids
				stmt = (
					sa.select(DocumentsStore.chunks)
					.filter(*doc_filters)
				)
				result = session.execute(stmt).fetchall()
				chunk_ids = [str(c) for res in result for c in res.chunks]

				# get embeddings
				return self._similarity_search(session, query, chunk_ids, k)
		except Exception as e:
			raise DbException('Error: performing doc search in vectordb') from e

	# modified from langchain_postgres.vectorstores
	def _similarity_search(
		self,
		session: orm.Session,
		query: str,
		chunk_ids: list[str],
		k: int = 20,
	) -> list[Document]:
		embedding = self.client.embeddings.embed_query(query)
		collection = self.client.get_collection(session)
		if not collection:
			raise DbException('Collection not found')

		filter_by = [
			self.client.EmbeddingStore.collection_id == collection.uuid,
			self.client.EmbeddingStore.id.in_(chunk_ids),
		]

		results = (
			session.query(
				self.client.EmbeddingStore,
				self.client.distance_strategy(embedding).label('distance'),
			)
			.filter(*filter_by)
			.order_by(sa.asc('distance'))
			.join(
				self.client.CollectionStore,
				self.client.EmbeddingStore.collection_id == self.client.CollectionStore.uuid,
			)
			.limit(k)
			.all()
		)

		return [
			Document(
				id=str(result.EmbeddingStore.id),
				page_content=result.EmbeddingStore.document,
				metadata=result.EmbeddingStore.cmetadata,
			) for result in results
		]
