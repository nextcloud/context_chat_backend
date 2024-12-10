from abc import ABC, abstractmethod
from typing import Any

from fastapi import UploadFile
from langchain.schema import Document
from langchain.schema.embeddings import Embeddings
from langchain.schema.vectorstore import VectorStore

from ..chain.types import InDocument, ScopeType
from ..utils import timed
from .types import UpdateAccessOp


class BaseVectorDB(ABC):
	client: Any = None
	embedding: Any = None

	@abstractmethod
	def __init__(self, embedding: Embeddings | None = None, **kwargs):
		'''
		Raises
		------
		DbException
		'''
		self.embedding = embedding

	@abstractmethod
	def get_users(self) -> list[str]:
		'''
		Returns a list of all user IDs.

		Returns
		-------
		list[str]
			List of user IDs.

		Raises
		------
		DbException
		'''

	@abstractmethod
	def get_instance(self) -> VectorStore:
		'''
		Creates and returns the langchain vectordb client object.

		Args
		----

		Returns
		-------
		VectorStore
			Client object for the VectorDB

		Raises
		------
		DbException
		'''

	@abstractmethod
	def add_indocuments(self, indocuments: list[InDocument]) -> list[str]:
		'''
		Adds the given indocuments to the vectordb and updates the docs + access tables.

		Args
		----
		indocuments: list[InDocument]
			List of InDocument objects to add.

		Returns
		-------
		list[str]
			List of source ids that were successfully added.
		'''

	@abstractmethod
	def sources_to_embed(
		self,
		sources: list[UploadFile],
	) -> list[str]:
		'''
		Returns a list of source ids that need to be embedded.

		Args
		----
		sources: list[UploadFile]
			List of source ids to check.

		Returns
		-------
		list[str]
			List of source ids to embed.
		'''

	@abstractmethod
	def update_access(
		self,
		op: UpdateAccessOp,
		user_ids: list[str],
		source_id: str,
	):
		'''
		Updates the access for the given users and source.
		This is used to allow or deny access to sources.

		Args
		----
		op: UpdateAccessOp
			Operation to perform.
		user_ids: list[str]
			User IDs to grant/deny access to.
		source_id: str
			Source ID to update access for.

		Raises
		------
		SafeDbException
		'''
		...

	@abstractmethod
	def update_access_provider(
		self,
		op: UpdateAccessOp,
		user_ids: list[str],
		provider_id: str,
	):
		'''
		Update the access for the given users and provider.
		This is used to allow or deny access to sources from a provider.

		Args
		----
		op: UpdateAccessOp
			Operation to perform.
		user_ids: list[str]
			User IDs to grant/deny access to.
		source_id: str
			Source ID to update access for.

		Raises
		------
		# todo
		SafeDbException
		'''
		...

	@abstractmethod
	def delete_source_ids(self, source_ids: list[str]):
		'''
		Deletes all documents with the given source ids.

		Args
		----
		ids: list[str]
			List of source ids to delete.
		'''
		...

	@abstractmethod
	def delete_provider(self, provider_key: str):
		'''
		Delete all documents with the given provider key.

		Args
		----
		provider_key: str
			Provider key to delete by.
		'''
		...

	@abstractmethod
	def decl_update_access(
		self,
		user_ids: list[str],
		source_id: str,
	):
		'''
		Updates the absolute user access for the given source.
		This is used to allow or deny access to sources.

		Args
		----
		user_ids: list[str]
			User IDs to grant access to.
		source_id: str
			Source ID to update access for.

		Raises
		------
		SafeDbException
		'''
		...

	@abstractmethod
	def delete_user(self, user_id: str):
		'''
		Deletes access for the given user.
		And deletes all documents that no longer have any users with access.

		Args
		----
		user_id: str
			User ID to delete.
		'''
		...

	@timed
	@abstractmethod
	def doc_search(
		self,
		user_id: str,
		query: str,
		k: int,
		scope_type: ScopeType | None = None,
		scope_list: list[str] | None = None,
	) -> list[Document]:
		'''
		Searches for documents in the vectordb.

		Args
		----
		user_id: str
			User ID to search for.
		query: str
			Query to search for.
		k: int
			Number of results to return.

		Returns
		-------
		list[Document]
			List of Document objects.

		Raises
		------
		SafeDbException
		'''
		...
