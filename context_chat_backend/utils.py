from functools import wraps
from os import getenv
from typing import Any, TypeVar

from fastapi import FastAPI
from fastapi.responses import JSONResponse as FastAPIJSONResponse

from .ocs_utils import ocs_call

T = TypeVar('T')


def value_of(value: T, default: T | None = None) -> T | None:
	if value is None:
		return default

	if isinstance(value, str) and value.strip() == '':
		return default

	if isinstance(value, list) and len(value) == 0:
		return default

	return value


# class name/index name is capitalized (user1 => User1) maybe because it is a class name,
# so the solution is to use Vector_user1 instead of user1
COLLECTION_NAME = lambda user_id: f'Vector_{user_id}'


def to_int(value: Any | None, default: int = 0) -> int:
	if value is None:
		return default

	try:
		return int(value)
	except ValueError:
		return default


def JSONResponse(
	content: Any = 'ok',
	status_code: int = 200,
	**kwargs
) -> FastAPIJSONResponse:
	'''
	Wrapper for FastAPI JSONResponse
	'''
	if isinstance(content, str):
		if status_code >= 400:
			return FastAPIJSONResponse(
				content={ 'error': content },
				status_code=status_code,
				**kwargs,
			)
		return FastAPIJSONResponse(
			content={ 'message': content },
			status_code=status_code,
			**kwargs,
		)

	return FastAPIJSONResponse(content, status_code, **kwargs)


def enabled_guard(app: FastAPI):
	def decorator(func: callable):
		'''
		Decorator to check if the service is enabled
		'''
		@wraps(func)
		def wrapper(*args, **kwargs):
			if getenv('DISABLE_AAA', '0') == '0' and not app.extra.get('ENABLED', False):
				return JSONResponse('Context Chat is disabled, enable it from AppAPI to use it.', 503)

			return func(*args, **kwargs)

		return wrapper

	return decorator


def update_progress(progress: int):
	ocs_call(
		method='PUT',
		path=f'/ocs/v1.php/apps/app_api/apps/status/{getenv("APP_ID")}',
		json_data={ 'progress': min(100, progress) },
	)
