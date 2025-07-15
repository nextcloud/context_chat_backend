#
# SPDX-FileCopyrightText: 2024 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
from typing import Literal

from pydantic import BaseModel

__all__ = [
	'EmbeddingException',
	'LoaderException',
	'TConfig',
	'TEmbeddingAuthApiKey',
	'TEmbeddingAuthBasic',
	'TEmbeddingLlama',
	'TEmbeddingOAI',
]

class TEmbeddingAuthApiKey(BaseModel):
	apikey: str

class TEmbeddingAuthBasic(BaseModel):
	username: str
	password: str

class TEmbeddingLlama(BaseModel):
	base_url: str = 'http://localhost:5000/v1'
	workers: int = 1
	request_timeout: int = 1750
	offload_after_mins: int = 15
	llama: dict
	auth: None = None
	model: None = None

class TEmbeddingOAI(BaseModel):
	base_url: str
	workers: int = 0
	auth: TEmbeddingAuthApiKey | TEmbeddingAuthBasic | Literal['from_env'] | None = None
	model: str | None = None
	request_timeout: int = 1750
	llama: None = None


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
	embedding: TEmbeddingLlama | TEmbeddingOAI
	llm: tuple[str, dict]


class LoaderException(Exception):
	...


class EmbeddingException(Exception):
	...
