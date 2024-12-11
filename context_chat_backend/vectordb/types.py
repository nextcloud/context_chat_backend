from enum import Enum


class DbException(Exception):
	...


class SafeDbException(Exception):
	...


class UpdateAccessOp(Enum):
	allow = 'allow'
	deny = 'deny'
