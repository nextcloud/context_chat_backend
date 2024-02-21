from abc import ABC, abstractmethod
from typing import List, Optional

from langchain.schema.embeddings import Embeddings
from langchain.vectorstores import VectorStore


class BaseVectorDB(ABC):
	client = None
	embedding = None

	@abstractmethod
	def __init__(self, embedding: Optional[Embeddings] = None, **kwargs):
		self.embedding = embedding

	@abstractmethod
	def get_user_client(
			self,
			user_id: str,
			embedding: Optional[Embeddings] = None  # Use this embedding if not None or use global embedding
		) -> Optional[VectorStore]:
		'''
		Creates and returns the langchain vectordb client object for the given user_id.

		Args
		----
		user_id: str
			User ID for which to create the client object.
		embedding: Optional[Embeddings]
			Embeddings object to use for embedding documents.

		Returns
		-------
		Optional[VectorStore]
			Client object for the VectorDB or None if error occurs.
		'''

	@abstractmethod
	def setup_schema(self, user_id: str) -> None:
		'''
		Sets up the schema for the VectorDB

		Args
		----
		user_id: str
			User ID for which to setup the schema.

		Returns
		-------
		None
		'''

	@abstractmethod
	def get_objects_from_metadata(
		self,
		user_id: str,
		metadata_key: str,
		values: List[str],
		contains: bool = False,
	) -> dict:
		'''
		Get all objects with the given metadata key and values.
		(Only gets the following fields: [id, 'metadata_key', modified])

		Args
		----
		user_id: str
			User ID for whose database to get the sources.
		metadata_key: str
			Metadata key to get.
		values: List[str]
			List of metadata names to get.
		contains: bool
			If True, gets all objects that contain any of the given values,
			otherwise gets all objects that have the given values.

		Returns
		-------
		List[dict]
			if error occurs: {}

			otherwise:

			{
				[metadata_key: str]: {
					'id': str,
					'modified': str,
				}
			}
		'''

	def delete_by_ids(self, user_id: str, ids: list[str]) -> Optional[bool]:
		'''
		Deletes all documents with the given ids for the given user.

		Args
		----
		user_id: str
			User ID from whose database to delete the documents.
		ids: list[str]
			List of document ids to delete.

		Returns
		-------
		Optional[bool]
			Optional[bool]: True if deletion is successful,
			False otherwise, None if not implemented.
		'''
		if len(ids) == 0:
			return True

		user_client = self.get_user_client(user_id)
		if user_client is None:
			return False

		return user_client.delete(ids)
