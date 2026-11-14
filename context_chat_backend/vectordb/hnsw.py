#
# SPDX-FileCopyrightText: 2026 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
'''Helpers for the optional HNSW index on the embeddings table.

The embedding column is created as an untyped `vector` unless `embedding_length` is set, and pgvector can only
index a column with a fixed dimension. The index is therefore built on `embedding::vector(N)`, which needs no
table rewrite, and searches use the same cast so the planner can pick the index.
'''

import re
from dataclasses import dataclass

HNSW_INDEX_NAME = 'ccb_embedding_hnsw_idx'
# pgvector cannot build an HNSW index on `vector` columns with more dimensions than this
HNSW_MAX_DIMENSIONS = 2000

# langchain_postgres DistanceStrategy values -> pgvector operator classes
OPERATOR_CLASSES = {
	'cosine': 'vector_cosine_ops',
	'l2': 'vector_l2_ops',
	'inner': 'vector_ip_ops',
}

_INDEX_DIMS_RE = re.compile(r'::vector\((\d+)\)')


@dataclass(frozen=True)
class HnswConfig:
	m: int = 16
	ef_construction: int = 64

	def __post_init__(self):
		# same bounds as pgvector, checked here so a bad config fails at startup and not in the index build
		if not isinstance(self.m, int) or not 2 <= self.m <= 100:
			raise ValueError(f'hnsw_index.m must be an integer between 2 and 100, got {self.m!r}')
		if not isinstance(self.ef_construction, int) or not 4 <= self.ef_construction <= 1000:
			raise ValueError(
				f'hnsw_index.ef_construction must be an integer between 4 and 1000, got {self.ef_construction!r}'
			)
		if self.ef_construction < 2 * self.m:
			raise ValueError(
				f'hnsw_index.ef_construction ({self.ef_construction}) must be at least twice m ({self.m})'
			)

	@classmethod
	def from_config(cls, value: dict | bool | None) -> 'HnswConfig | None':
		'''`hnsw_index: true` uses the defaults, a mapping overrides them, missing or false disables the index.'''
		if value is None or value is False:
			return None
		if value is True:
			return cls()
		if not isinstance(value, dict):
			raise ValueError(f'hnsw_index must be true, false or a mapping with m and ef_construction, got {value!r}')
		unknown = set(value) - {'m', 'ef_construction'}
		if unknown:
			raise ValueError(f'Unknown hnsw_index option(s): {", ".join(sorted(unknown))}')
		return cls(**value)


def pick_dimension(dim_counts: list[tuple[int, int]]) -> int | None:
	'''Return the dimension shared by most embeddings, or None if there are no embeddings.

	dim_counts holds (dimension, number of rows) pairs.
	'''
	if not dim_counts:
		return None
	return max(dim_counts, key=lambda dc: dc[1])[0]


def operator_class(distance_strategy: str) -> str:
	# PGVector stores a DistanceStrategy enum unless a plain string comes from the config
	try:
		return OPERATOR_CLASSES[getattr(distance_strategy, 'value', distance_strategy)]
	except KeyError:
		raise ValueError(f'No HNSW operator class for distance strategy {distance_strategy!r}') from None


def create_index_sql(table: str, dims: int, distance_strategy: str, config: HnswConfig) -> str:
	# DDL cannot take bind parameters, so every interpolated value is validated here
	if not isinstance(dims, int) or not 1 <= dims <= HNSW_MAX_DIMENSIONS:
		raise ValueError(f'HNSW indexes support 1 to {HNSW_MAX_DIMENSIONS} dimensions, got {dims!r}')
	if not table.isidentifier():
		raise ValueError(f'Invalid table name: {table!r}')

	return (
		f'CREATE INDEX CONCURRENTLY IF NOT EXISTS {HNSW_INDEX_NAME} ON {table}'
		f' USING hnsw ((embedding::vector({dims})) {operator_class(distance_strategy)})'
		f' WITH (m = {config.m}, ef_construction = {config.ef_construction})'
	)


def dims_from_index_def(index_def: str) -> int | None:
	'''Read the dimension back from the index definition returned by pg_get_indexdef().

	Returns None when the index is on the column itself: on a `vector(N)` column (set with `embedding_length`)
	Postgres drops the cast, and searches can use the column as is.
	'''
	match = _INDEX_DIMS_RE.search(index_def)
	return int(match.group(1)) if match else None


def supports_iterative_scan(pgvector_version: str) -> bool:
	'''hnsw.iterative_scan was added in pgvector 0.8.0.'''
	try:
		major, minor = (int(p) for p in pgvector_version.split('.')[:2])
	except ValueError:
		return False
	return (major, minor) >= (0, 8)
