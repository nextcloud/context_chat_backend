from enum import Enum
from typing import TypedDict


class DbException(Exception):
	...


class MetadataFilter(TypedDict):
	metadata_key: str
	values: list[str]


class UpdateAccessOp(Enum):
	allow = 'allow'
	deny = 'deny'
