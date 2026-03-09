#
# SPDX-FileCopyrightText: 2024 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
from enum import Enum
from io import BytesIO
from typing import Self

from pydantic import BaseModel, field_validator

from .mimetype_list import SUPPORTED_MIMETYPES
from .utils import is_valid_provider_id, is_valid_source_id

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
FILES_PROVIDER_ID = 'files__default'


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
	batch_size: int = 100  # max texts per embedding API request, 0 = no batching
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


class AppRole(str, Enum):
	NORMAL = 'normal'
	INDEXING = 'indexing'
	RP = 'rp'


class CommonSourceItem(BaseModel):
	userIds: list[str]
	reference: str  # source_id of the form "appId__providerId: itemId"
	title: str
	modified: int | str  # todo: int/string?
	type: str
	provider: str
	size: int

	@field_validator('modified', mode='before')
	@classmethod
	def validate_modified(cls, v):
		if isinstance(v, int):
			return v
		if isinstance(v, str):
			try:
				return int(v)
			except ValueError as e:
				raise ValueError(f'Invalid modified value: {v}') from e
		raise ValueError(f'Invalid modified type: {type(v)}')

	@field_validator('reference', 'title', 'type', 'provider')
	@classmethod
	def validate_strings_non_empty(cls, v):
		if not isinstance(v, str) or v.strip() == '':
			raise ValueError('Must be a non-empty string')
		return v.strip()

	@field_validator('userIds', mode='after')
	def validate_user_ids(self) -> Self:
		if (
			not isinstance(self.userIds, list)
			or not all(
				isinstance(uid, str)
				and uid.strip() != ''
				for uid in self.userIds
			)
			or len(self.userIds) == 0
		):
			raise ValueError('userIds must be a non-empty list of non-empty strings')
		self.userIds = [uid.strip() for uid in self.userIds]
		return self

	@field_validator('reference', mode='after')
	def validate_reference_format(self) -> Self:
		# validate reference format: "appId__providerId: itemId"
		if not is_valid_source_id(self.reference):
			raise ValueError('Invalid reference format, must be "appId__providerId: itemId"')
		return self

	@field_validator('provider', mode='after')
	def validate_provider_format(self) -> Self:
		# validate provider format: "appId__providerId"
		if not is_valid_provider_id(self.provider):
			raise ValueError('Invalid provider format, must be "appId__providerId"')
		return self

	@field_validator('type', mode='after')
	def validate_type(self) -> Self:
		if self.reference.startswith(FILES_PROVIDER_ID) and self.type not in SUPPORTED_MIMETYPES:
			raise ValueError(f'Unsupported file type: {self.type} for reference {self.reference}')
		return self

	@field_validator('size', mode='after')
	def validate_size(self) -> Self:
		if not isinstance(self.size, int) or self.size < 0:
			raise ValueError(f'Invalid size value: {self.size}, must be a non-negative integer')
		return self


class ReceivedFileItem(CommonSourceItem):
	content: None


class SourceItem(CommonSourceItem):
	'''
	Used for the unified queue of items to process, after fetching the content for files
	and for directly fetched content providers.
	'''
	content: str | BytesIO

	@field_validator('content')
	@classmethod
	def validate_content(cls, v):
		if isinstance(v, str):
			if v.strip() == '':
				raise ValueError('Content must be a non-empty string')
			return v.strip()
		if isinstance(v, BytesIO):
			if v.getbuffer().nbytes == 0:
				raise ValueError('Content must be a non-empty BytesIO')
			return v
		raise ValueError('Content must be either a non-empty string or a non-empty BytesIO')


class FilesQueueItem(BaseModel):
	files: dict[int, ReceivedFileItem]  # [db id]: FileItem
	content_providers: dict[int, SourceItem]  # [db id]: SourceItem


class IndexingException(Exception):
	retryable: bool = False

	def __init__(self, message: str, retryable: bool = False):
		super().__init__(message)
		self.retryable = retryable


class IndexingError(BaseModel):
	error: str
	retryable: bool = False
