#
# SPDX-FileCopyrightText: 2024 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
import logging

from ..dyn_loader import VectorDBLoader
from .base import BaseVectorDB
from .types import DbException, UpdateAccessOp

logger = logging.getLogger('ccb.vectordb')

# todo: return source ids that were successfully deleted
def delete_by_source(vectordb_loader: VectorDBLoader, source_ids: list[str]):
	db: BaseVectorDB = vectordb_loader.load()
	logger.debug('deleting sources by id', extra={ 'source_ids': source_ids })
	try:
		db.delete_source_ids(source_ids)
	except Exception as e:
		raise DbException('Error: Vectordb delete_source_ids error') from e


def delete_by_provider(vectordb_loader: VectorDBLoader, provider_key: str):
	db: BaseVectorDB = vectordb_loader.load()
	logger.debug(f'deleting sources by provider: {provider_key}')
	db.delete_provider(provider_key)


def delete_user(vectordb_loader: VectorDBLoader, user_id: str):
	db: BaseVectorDB = vectordb_loader.load()
	logger.debug(f'deleting user from db: {user_id}')
	db.delete_user(user_id)


def delete_folder(vectordb_loader: VectorDBLoader, folder_path: str):
	db: BaseVectorDB = vectordb_loader.load()
	logger.debug(f'deleting folder "{folder_path}" from db')
	db.delete_folder(folder_path)


def update_access(
	vectordb_loader: VectorDBLoader,
	op: UpdateAccessOp,
	user_ids: list[str],
	source_id: str,
):
	db: BaseVectorDB = vectordb_loader.load()
	logger.debug('updating access', extra={ 'op': op, 'user_ids': user_ids, 'source_id': source_id })
	db.update_access(op, user_ids, source_id)


def update_access_provider(
	vectordb_loader: VectorDBLoader,
	op: UpdateAccessOp,
	user_ids: list[str],
	provider_id: str,
):
	db: BaseVectorDB = vectordb_loader.load()
	logger.debug('updating access by provider', extra={ 'op': op, 'user_ids': user_ids, 'provider_id': provider_id })
	db.update_access_provider(op, user_ids, provider_id)


def decl_update_access(
	vectordb_loader: VectorDBLoader,
	user_ids: list[str],
	source_id: str,
):
	db: BaseVectorDB = vectordb_loader.load()
	logger.debug('decl update access', extra={ 'user_ids': user_ids, 'source_id': source_id })
	db.decl_update_access(user_ids, source_id)

def count_documents_by_provider(vectordb_loader: VectorDBLoader):
	db: BaseVectorDB = vectordb_loader.load()
	logger.debug('counting documents by provider')
	return db.count_documents_by_provider()
