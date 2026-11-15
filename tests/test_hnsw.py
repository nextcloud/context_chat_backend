#
# SPDX-FileCopyrightText: 2026 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
'''Tests for the HNSW index helpers.'''

from enum import StrEnum

import pytest

from context_chat_backend.vectordb import hnsw
from context_chat_backend.vectordb.hnsw import HnswConfig


class TestHnswConfig:
	@pytest.mark.parametrize('value', [None, False])
	def test_disabled(self, value):
		assert HnswConfig.from_config(value) is None

	def test_true_uses_defaults(self):
		assert HnswConfig.from_config(True) == HnswConfig(m=16, ef_construction=64)

	def test_mapping_overrides_defaults(self):
		assert HnswConfig.from_config({'m': 24}) == HnswConfig(m=24, ef_construction=64)
		assert HnswConfig.from_config({'m': 8, 'ef_construction': 100}) == HnswConfig(m=8, ef_construction=100)

	@pytest.mark.parametrize('value', [
		{'m': 1},
		{'m': 101, 'ef_construction': 1000},
		{'m': '16'},
		{'ef_construction': 3},
		{'ef_construction': 1001},
		{'m': 40, 'ef_construction': 64},  # pgvector requires ef_construction >= 2 * m
		{'ef_search': 40},
		'yes',
		16,
	])
	def test_invalid(self, value):
		with pytest.raises(ValueError):
			HnswConfig.from_config(value)


class TestPickDimension:
	def test_no_embeddings(self):
		assert hnsw.pick_dimension([]) is None

	def test_single_dimension(self):
		assert hnsw.pick_dimension([(1024, 678_000)]) == 1024

	def test_most_common_dimension_wins(self):
		assert hnsw.pick_dimension([(768, 12), (1024, 5000), (384, 40)]) == 1024


class TestCreateIndexSql:
	def test_cosine(self):
		sql = hnsw.create_index_sql('langchain_pg_embedding', 1024, 'cosine', HnswConfig())
		assert sql == (
			'CREATE INDEX CONCURRENTLY IF NOT EXISTS ccb_embedding_hnsw_idx ON langchain_pg_embedding'
			' USING hnsw ((embedding::vector(1024)) vector_cosine_ops) WITH (m = 16, ef_construction = 64)'
		)

	@pytest.mark.parametrize(('strategy', 'ops'), [('l2', 'vector_l2_ops'), ('inner', 'vector_ip_ops')])
	def test_other_distance_strategies(self, strategy, ops):
		sql = hnsw.create_index_sql('langchain_pg_embedding', 768, strategy, HnswConfig(m=8, ef_construction=32))
		assert f'(embedding::vector(768)) {ops}' in sql
		assert 'WITH (m = 8, ef_construction = 32)' in sql

	def test_distance_strategy_enum(self):
		# same shape as langchain_postgres' DistanceStrategy, which PGVector stores by default
		class DistanceStrategy(StrEnum):
			COSINE = 'cosine'

		sql = hnsw.create_index_sql('langchain_pg_embedding', 1024, DistanceStrategy.COSINE, HnswConfig())
		assert 'vector_cosine_ops' in sql

	def test_unknown_distance_strategy(self):
		with pytest.raises(ValueError, match='distance strategy'):
			hnsw.create_index_sql('langchain_pg_embedding', 1024, 'hamming', HnswConfig())

	@pytest.mark.parametrize('dims', [0, 2001, '1024', None])
	def test_invalid_dimension(self, dims):
		with pytest.raises(ValueError, match='dimensions'):
			hnsw.create_index_sql('langchain_pg_embedding', dims, 'cosine', HnswConfig())

	def test_invalid_table_name(self):
		with pytest.raises(ValueError, match='table name'):
			hnsw.create_index_sql('emb; DROP TABLE docs', 1024, 'cosine', HnswConfig())


class TestDimsFromIndexDef:
	def test_round_trip(self):
		# what pg_get_indexdef() returns for the index created by create_index_sql()
		index_def = (
			'CREATE INDEX ccb_embedding_hnsw_idx ON public.langchain_pg_embedding'
			' USING hnsw (((embedding)::vector(1024)) vector_cosine_ops) WITH (m=\'16\', ef_construction=\'64\')'
		)
		assert hnsw.dims_from_index_def(index_def) == 1024

	def test_typed_column(self):
		# Postgres drops the cast when the column is already vector(1024)
		index_def = (
			'CREATE INDEX ccb_embedding_hnsw_idx ON public.langchain_pg_embedding'
			' USING hnsw (embedding vector_cosine_ops) WITH (m=\'16\', ef_construction=\'64\')'
		)
		assert hnsw.dims_from_index_def(index_def) is None


@pytest.mark.parametrize(('version', 'expected'), [
	('0.5.1', False),
	('0.7.4', False),
	('0.8.0', True),
	('0.8.1', True),
	('1.0.0', True),
	('', False),
	('dev', False),
])
def test_supports_iterative_scan(version, expected):
	assert hnsw.supports_iterative_scan(version) is expected
