#
# SPDX-FileCopyrightText: 2024 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
import logging

from ..dyn_loader import VectorDBLoader
from .base import BaseVectorDB
from .types import UpdateAccessOp

logger = logging.getLogger('ccb.vectordb')


def delete_by_source(vectordb_loader: VectorDBLoader, source_ids: list[str]):
	'''
	Raises
	------
	DbException
	LoaderException
	'''
	db: BaseVectorDB = vectordb_loader.load()
	logger.debug('deleting sources by id', extra={ 'source_ids': source_ids })
	db.delete_source_ids(source_ids)


def delete_by_provider(vectordb_loader: VectorDBLoader, provider_key: str):
	'''
	Raises
	------
	DbException
	LoaderException
	'''
	db: BaseVectorDB = vectordb_loader.load()
	logger.debug(f'deleting sources by provider: {provider_key}')
	db.delete_provider(provider_key)


def delete_user(vectordb_loader: VectorDBLoader, user_id: str):
	'''
	Raises
	------
	DbException
	LoaderException
	'''
	db: BaseVectorDB = vectordb_loader.load()
	logger.debug(f'deleting user from db: {user_id}')
	db.delete_user(user_id)


def update_access(
	vectordb_loader: VectorDBLoader,
	op: UpdateAccessOp,
	user_ids: list[str],
	source_id: str,
):
	'''
	Raises
	------
	DbException
	LoaderException
	SafeDbException
	'''
	db: BaseVectorDB = vectordb_loader.load()
	logger.debug('updating access', extra={ 'op': op, 'user_ids': user_ids, 'source_id': source_id })
	db.update_access(op, user_ids, source_id)


def update_access_provider(
	vectordb_loader: VectorDBLoader,
	op: UpdateAccessOp,
	user_ids: list[str],
	provider_id: str,
):
	'''
	Raises
	------
	DbException
	LoaderException
	SafeDbException
	'''
	db: BaseVectorDB = vectordb_loader.load()
	logger.debug('updating access by provider', extra={ 'op': op, 'user_ids': user_ids, 'provider_id': provider_id })
	db.update_access_provider(op, user_ids, provider_id)


def decl_update_access(
	vectordb_loader: VectorDBLoader,
	user_ids: list[str],
	source_id: str,
):
	'''
	Raises
	------
	DbException
	LoaderException
	SafeDbException
	'''
	db: BaseVectorDB = vectordb_loader.load()
	logger.debug('decl update access', extra={ 'user_ids': user_ids, 'source_id': source_id })
	db.decl_update_access(user_ids, source_id)

def count_documents_by_provider(vectordb_loader: VectorDBLoader):
	'''
	Raises
	------
	DbException
	LoaderException
	'''
	db: BaseVectorDB = vectordb_loader.load()
	logger.debug('counting documents by provider')
	return db.count_documents_by_provider()
