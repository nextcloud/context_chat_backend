#
# SPDX-FileCopyrightText: 2026 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from context_chat_backend.vectordb import pgvector

CONFIG_IMPORT = (
	'from context_chat_backend.vectordb.pgvector import PG_BATCH_SIZE, PG_SEARCH_BATCH_SIZE; '
	'print(PG_BATCH_SIZE, PG_SEARCH_BATCH_SIZE)'
)
INVALID_CONFIG_IMPORT = '''
try:
    import context_chat_backend.vectordb.pgvector
except ValueError as exc:
    cause = type(exc.__cause__).__name__ if exc.__cause__ is not None else None
    print(f'{type(exc).__name__}: {exc}|cause={cause}')
else:
    raise SystemExit('Expected invalid batch size to raise ValueError')
'''
SEARCH_BATCH_SIZE_ENV = 'CCB_PG_SEARCH_BATCH_SIZE'


class FakeColumn:
	def __eq__(self, value):
		return ('equals', value)

	def in_(self, values):
		return ('in', list(values))


class FakeQuery:
	def __init__(self, session):
		self.session = session
		self.chunk_ids = []
		self.limit_count = 0

	def filter(self, *conditions):
		condition = next(condition for condition in conditions if condition[0] == 'in')
		self.chunk_ids = condition[1]
		self.session.batches.append(self.chunk_ids)
		return self

	def join(self, *_args):
		return self

	def order_by(self, *_args):
		return self

	def limit(self, count):
		self.limit_count = count
		return self

	def __iter__(self):
		results = [self.session.results[chunk_id] for chunk_id in self.chunk_ids]
		return iter(sorted(results, key=lambda result: result.distance)[:self.limit_count])


class FakeSession:
	def __init__(self, results):
		self.results = results
		self.batches = []

	def query(self, *_args):
		return FakeQuery(self)


class FakeSessionContext:
	def __init__(self, session):
		self.session = session

	def __enter__(self):
		return self.session

	def __exit__(self, *_args):
		return False


def _result(chunk_id: str, distance: float):
	return SimpleNamespace(
		EmbeddingStore=SimpleNamespace(
			id=chunk_id,
			document=f'text for {chunk_id}',
			cmetadata={'source': f'source for {chunk_id}'},
		),
		distance=distance,
	)


def _make_search_db(results):
	embedding_store = SimpleNamespace(collection_id=FakeColumn(), id=FakeColumn())
	collection_store = SimpleNamespace(uuid=FakeColumn())
	client = SimpleNamespace(
		embeddings=SimpleNamespace(embed_query=Mock(return_value=[0.1, 0.2])),
		get_collection=Mock(return_value=SimpleNamespace(uuid='collection-id')),
		EmbeddingStore=embedding_store,
		CollectionStore=collection_store,
		distance_strategy=Mock(return_value=SimpleNamespace(label=Mock(return_value='distance'))),
	)
	db = object.__new__(pgvector.VectorDB)
	db.client = client
	return db, FakeSession(results)


def _run_config_import(value: str | None = None, script: str = CONFIG_IMPORT) -> subprocess.CompletedProcess:
	env = os.environ.copy()
	env.pop(SEARCH_BATCH_SIZE_ENV, None)
	env['PYTHON_DOTENV_DISABLED'] = '1'
	if value is not None:
		env[SEARCH_BATCH_SIZE_ENV] = value
	return subprocess.run(  # noqa: S603
		[sys.executable, '-c', script],
		cwd=Path(__file__).resolve().parents[1],
		env=env,
		capture_output=True,
		check=True,
		text=True,
	)


def test_search_batch_size_defaults_to_existing_batch_size():
	result = _run_config_import()

	assert result.stdout.strip() == '50000 50000'


def test_search_batch_size_uses_environment_value():
	result = _run_config_import('10000')

	assert result.stdout.strip() == '50000 10000'


@pytest.mark.parametrize(('value', 'cause'), [
	('0', None),
	('-10', None),
	('abc', 'ValueError'),
])
def test_search_batch_size_rejects_invalid_environment_values(value: str, cause: str | None):
	result = _run_config_import(value, INVALID_CONFIG_IMPORT)

	assert result.stdout.strip() == f'ValueError: CCB_PG_SEARCH_BATCH_SIZE must be a positive integer|cause={cause}'


def test_similarity_search_splits_chunk_ids_using_configured_batch_size(monkeypatch):
	monkeypatch.setattr(pgvector, 'PG_SEARCH_BATCH_SIZE', 2)
	chunk_ids = [f'chunk-{i}' for i in range(5)]
	results = {chunk_id: _result(chunk_id, float(i)) for i, chunk_id in enumerate(chunk_ids)}
	db, session = _make_search_db(results)

	documents = db._similarity_search(session, 'query', chunk_ids, k=5)

	assert session.batches == [chunk_ids[:2], chunk_ids[2:4], chunk_ids[4:]]
	assert {document.id for document in documents} == set(chunk_ids)


def test_similarity_search_globally_sorts_batches_and_returns_closest_top_k(monkeypatch):
	monkeypatch.setattr(pgvector, 'PG_SEARCH_BATCH_SIZE', 2)
	chunk_ids = [f'chunk-{i}' for i in range(5)]
	results = {
		'chunk-0': _result('chunk-0', 0.3),
		'chunk-1': _result('chunk-1', 0.9),
		'chunk-2': _result('chunk-2', 0.1),
		'chunk-3': _result('chunk-3', 0.5),
		'chunk-4': _result('chunk-4', 0.2),
	}
	db, session = _make_search_db(results)

	documents = db._similarity_search(session, 'query', chunk_ids, k=2)

	assert [document.id for document in documents] == ['chunk-2', 'chunk-4']


def test_search_batch_size_does_not_change_document_insertion_batches(monkeypatch):
	monkeypatch.setattr(pgvector, 'PG_SEARCH_BATCH_SIZE', 1)
	monkeypatch.setattr(pgvector, 'PG_BATCH_SIZE', 10)
	session = SimpleNamespace(add=Mock(), commit=Mock())
	db = object.__new__(pgvector.VectorDB)
	db.session_maker = Mock(return_value=FakeSessionContext(session))
	db.client = SimpleNamespace(add_documents=Mock(side_effect=lambda batch: [str(len(batch))]))
	db.decl_update_access = Mock()
	indocument = SimpleNamespace(
		documents=list(range(5)),
		source_id='source-id',
		provider='provider',
		modified=0,
		userIds=[],
	)

	db.add_indocuments({1: indocument})

	assert [len(call.args[0]) for call in db.client.add_documents.call_args_list] == [2, 2, 1]
	assert pgvector.PG_BATCH_SIZE == 10
	assert pgvector.PG_SEARCH_BATCH_SIZE == 1


def test_search_batch_size_does_not_change_access_control_batches(monkeypatch):
	monkeypatch.setattr(pgvector, 'PG_SEARCH_BATCH_SIZE', 1)
	monkeypatch.setattr(pgvector, 'PG_BATCH_SIZE', 2)
	inserted_batches = []

	class FakeInsert:
		def values(self, rows):
			self.rows = rows
			return self

		def on_conflict_do_nothing(self, **_kwargs):
			return self

	def fake_insert(_table):
		return FakeInsert()

	def execute(statement):
		if isinstance(statement, FakeInsert):
			inserted_batches.append(statement.rows)
			return None
		return SimpleNamespace(fetchone=lambda: object())

	monkeypatch.setattr(pgvector.postgresql_dialects, 'insert', fake_insert)
	session = SimpleNamespace(execute=Mock(side_effect=execute), commit=Mock(), rollback=Mock())
	db = object.__new__(pgvector.VectorDB)
	user_ids = [f'user-{i}' for i in range(5)]

	db.update_access(pgvector.UpdateAccessOp.ALLOW, user_ids, 'source-id', session)

	assert [[row['uid'] for row in batch] for batch in inserted_batches] == [
		user_ids[:2],
		user_ids[2:4],
		user_ids[4:],
	]
	assert pgvector.PG_BATCH_SIZE == 2
	assert pgvector.PG_SEARCH_BATCH_SIZE == 1
