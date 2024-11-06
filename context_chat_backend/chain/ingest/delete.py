from ...dyn_loader import VectorDBLoader
from ...vectordb.base import BaseVectorDB


def delete_by_source(vectordb_loader: VectorDBLoader, user_id: str, source_names: list[str]) -> bool:
	db: BaseVectorDB = vectordb_loader.load()
	return db.delete(user_id, 'source', source_names)


def delete_by_provider(vectordb_loader: VectorDBLoader, user_id: str, providerKey: str) -> bool:
	db: BaseVectorDB = vectordb_loader.load()
	return db.delete(user_id, 'provider', [providerKey])


def delete_for_all_users(vectordb_loader: VectorDBLoader, providerKey: str) -> bool:
	db: BaseVectorDB = vectordb_loader.load()
	return db.delete_for_all_users('provider', [providerKey])
