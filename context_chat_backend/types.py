#
# SPDX-FileCopyrightText: 2024 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
import re
from enum import Enum
from io import BytesIO
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, BaseModel, Discriminator, field_validator, model_validator

from .mimetype_list import SUPPORTED_MIMETYPES
from .vectordb.types import UpdateAccessOp

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


def is_valid_source_id(source_id: str) -> bool:
	# note the ":" in the item id part
	return re.match(r'^[a-zA-Z0-9_-]+__[a-zA-Z0-9_-]+: [a-zA-Z0-9:-]+$', source_id) is not None


def is_valid_provider_id(provider_id: str) -> bool:
	return re.match(r'^[a-zA-Z0-9_-]+__[a-zA-Z0-9_-]+$', provider_id) is not None


def _validate_source_ids(source_ids: list[str]) -> list[str]:
	if (
		not isinstance(source_ids, list)
		or not all(isinstance(sid, str) and sid.strip() != '' for sid in source_ids)
		or len(source_ids) == 0
	):
		raise ValueError('sourceIds must be a non-empty list of non-empty strings')
	return [sid.strip() for sid in source_ids]


def _validate_source_id(source_id: str) -> str:
	return _validate_source_ids([source_id])[0]


def _validate_provider_id(provider_id: str) -> str:
	if not isinstance(provider_id, str) or not is_valid_provider_id(provider_id):
		raise ValueError('providerId must be a valid provider ID string')
	return provider_id


def _validate_user_ids(user_ids: list[str]) -> list[str]:
	if (
		not isinstance(user_ids, list)
		or not all(isinstance(uid, str) and uid.strip() != '' for uid in user_ids)
		or len(user_ids) == 0
	):
		raise ValueError('userIds must be a non-empty list of non-empty strings')
	return [uid.strip() for uid in user_ids]


def _validate_user_id(user_id: str) -> str:
	return _validate_user_ids([user_id])[0]


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
	userIds: Annotated[list[str], AfterValidator(_validate_user_ids)]
	# source_id of the form "appId__providerId: itemId"
	reference: Annotated[str, AfterValidator(_validate_source_id)]
	title: str
	modified: int
	type: str
	provider: Annotated[str, AfterValidator(_validate_provider_id)]
	size: float

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

	@field_validator('size')
	@classmethod
	def validate_size(cls, v):
		if isinstance(v, int | float) and v >= 0:
			return float(v)
		raise ValueError(f'Invalid size value: {v}, must be a non-negative number')

	@model_validator(mode='after')
	def validate_type(self) -> Self:
		if self.reference.startswith(FILES_PROVIDER_ID) and self.type not in SUPPORTED_MIMETYPES:
			raise ValueError(f'Unsupported file type: {self.type} for reference {self.reference}')
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

	class Config:
		# to allow BytesIO in content field
		arbitrary_types_allowed = True


class FilesQueueItems(BaseModel):
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


# PHP equivalent for reference:

# class ActionType {
# 	// { sourceIds: array<string> }
# 	public const DELETE_SOURCE_IDS = 'delete_source_ids';
# 	// { providerId: string }
# 	public const DELETE_PROVIDER_ID = 'delete_provider_id';
# 	// { userId: string }
# 	public const DELETE_USER_ID = 'delete_user_id';
# 	// { op: string, userIds: array<string>, sourceId: string }
# 	public const UPDATE_ACCESS_SOURCE_ID = 'update_access_source_id';
# 	// { op: string, userIds: array<string>, providerId: string }
# 	public const UPDATE_ACCESS_PROVIDER_ID = 'update_access_provider_id';
# 	// { userIds: array<string>, sourceId: string }
# 	public const UPDATE_ACCESS_DECL_SOURCE_ID = 'update_access_decl_source_id';
# }


class ActionPayloadDeleteSourceIds(BaseModel):
	sourceIds: Annotated[list[str], AfterValidator(_validate_source_ids)]


class ActionPayloadDeleteProviderId(BaseModel):
	providerId: Annotated[str, AfterValidator(_validate_provider_id)]


class ActionPayloadDeleteUserId(BaseModel):
	userId: Annotated[str, AfterValidator(_validate_user_id)]


class ActionPayloadUpdateAccessSourceId(BaseModel):
	op: UpdateAccessOp
	userIds: Annotated[list[str], AfterValidator(_validate_user_ids)]
	sourceId: Annotated[str, AfterValidator(_validate_source_id)]


class ActionPayloadUpdateAccessProviderId(BaseModel):
	op: UpdateAccessOp
	userIds: Annotated[list[str], AfterValidator(_validate_user_ids)]
	providerId: Annotated[str, AfterValidator(_validate_provider_id)]


class ActionPayloadUpdateAccessDeclSourceId(BaseModel):
	userIds: Annotated[list[str], AfterValidator(_validate_user_ids)]
	sourceId: Annotated[str, AfterValidator(_validate_source_id)]


class ActionType(str, Enum):
	DELETE_SOURCE_IDS = 'delete_source_ids'
	DELETE_PROVIDER_ID = 'delete_provider_id'
	DELETE_USER_ID = 'delete_user_id'
	UPDATE_ACCESS_SOURCE_ID = 'update_access_source_id'
	UPDATE_ACCESS_PROVIDER_ID = 'update_access_provider_id'
	UPDATE_ACCESS_DECL_SOURCE_ID = 'update_access_decl_source_id'


class CommonActionsQueueItem(BaseModel):
	id: int


class ActionsQueueItemDeleteSourceIds(CommonActionsQueueItem):
	type: Literal[ActionType.DELETE_SOURCE_IDS]
	payload: ActionPayloadDeleteSourceIds


class ActionsQueueItemDeleteProviderId(CommonActionsQueueItem):
	type: Literal[ActionType.DELETE_PROVIDER_ID]
	payload: ActionPayloadDeleteProviderId


class ActionsQueueItemDeleteUserId(CommonActionsQueueItem):
	type: Literal[ActionType.DELETE_USER_ID]
	payload: ActionPayloadDeleteUserId


class ActionsQueueItemUpdateAccessSourceId(CommonActionsQueueItem):
	type: Literal[ActionType.UPDATE_ACCESS_SOURCE_ID]
	payload: ActionPayloadUpdateAccessSourceId


class ActionsQueueItemUpdateAccessProviderId(CommonActionsQueueItem):
	type: Literal[ActionType.UPDATE_ACCESS_PROVIDER_ID]
	payload: ActionPayloadUpdateAccessProviderId


class ActionsQueueItemUpdateAccessDeclSourceId(CommonActionsQueueItem):
	type: Literal[ActionType.UPDATE_ACCESS_DECL_SOURCE_ID]
	payload: ActionPayloadUpdateAccessDeclSourceId


ActionsQueueItem = Annotated[
	ActionsQueueItemDeleteSourceIds
	| ActionsQueueItemDeleteProviderId
	| ActionsQueueItemDeleteUserId
	| ActionsQueueItemUpdateAccessSourceId
	| ActionsQueueItemUpdateAccessProviderId
	| ActionsQueueItemUpdateAccessDeclSourceId,
	Discriminator('type'),
]


class ActionsQueueItems(BaseModel):
	actions: dict[int, ActionsQueueItem]
