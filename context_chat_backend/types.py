#
# SPDX-FileCopyrightText: 2024 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
from pydantic import BaseModel

__all__ = [
	'EmbeddingException',
	'LoaderException',
	'TConfig',
	'TEmbedding',
]

class TEmbedding(BaseModel):
	protocol: str
	host: str
	port: int
	workers: int
	offload_after_mins: int
	request_timeout: int
	llama: dict


class TConfig(BaseModel):
	debug: bool
	uvicorn_log_level: str
	disable_aaa: bool
	httpx_verify_ssl: bool
	use_colors: bool
	uvicorn_workers: int
	embedding_chunk_size: int
	doc_parser_worker_limit: int

	vectordb: tuple[str, dict]
	embedding: TEmbedding
	llm: tuple[str, dict]


class LoaderException(Exception):
	...


class EmbeddingException(Exception):
	...

class RetryableEmbeddingException(EmbeddingException):
	"""
	Exception that indicates that the embedding request can be retried.

	This keeps the indexing loop running and adds to the retry list.
	The parent exception would break the loop and stop the indexing process.
	"""
