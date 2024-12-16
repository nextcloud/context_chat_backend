#
# SPDX-FileCopyrightText: 2024 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
from enum import Enum

from langchain.schema import Document
from pydantic import BaseModel
from typing_extensions import TypedDict

__all__ = [
	'ContextException',
	'InDocument',
	'LLMOutput',
	'ScopeType',
]


class InDocument(BaseModel):
	documents: list[Document]  # the split documents of the same source
	userIds: list[str]
	source_id: str
	provider: str
	modified: int


class ScopeType(Enum):
	PROVIDER = 'provider'
	SOURCE = 'source'


class ContextException(Exception):
	...


class LLMOutput(TypedDict):
	output: str
	sources: list[str]
