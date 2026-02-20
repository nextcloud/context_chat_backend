#
# SPDX-FileCopyrightText: 2024 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
from pydantic import BaseModel

__all__ = [
	'DEFAULT_EM_MODEL_ALIAS',
	'EmbeddingException',
	'LoaderException',
	'TConfig',
	'TEmbeddingAuthApiKey',
	'TEmbeddingAuthBasic',
	'TEmbeddingConfig',
]

DEFAULT_EM_MODEL_ALIAS = 'em_model'


class TEmbeddingAuthApiKey(BaseModel):
	apikey: str

class TEmbeddingAuthBasic(BaseModel):
	username: str
	password: str

class TEmbeddingConfig(BaseModel):
	base_url: str = 'http://localhost:5000/v1'
	workers: int = 1
	request_timeout: int = 1750
	model_name: str | None = DEFAULT_EM_MODEL_ALIAS
	auth: TEmbeddingAuthApiKey | TEmbeddingAuthBasic | None = None
	remote_service: bool = False
	llama: dict = dict()  # noqa: C408


class TConfig(BaseModel):
	debug: bool
	uvicorn_log_level: str
	disable_aaa: bool
	verify_ssl: bool
	use_colors: bool
	uvicorn_workers: int
	embedding_chunk_size: int
	doc_parser_worker_limit: int

	vectordb: tuple[str, dict]
	embedding: TEmbeddingConfig
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

class FatalEmbeddingException(EmbeddingException):
	"""
	Exception that indicates a fatal error in the embedding request.

	Either malformed request, authentication error, or other non-retryable error.
	"""
