#
# SPDX-FileCopyrightText: 2023 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
import multiprocessing as mp
import re
import traceback
from collections.abc import Callable
from functools import partial, wraps
from logging import error as log_error
from multiprocessing.connection import Connection
from os import getenv
from time import perf_counter_ns
from typing import Any, TypeGuard, TypeVar

from fastapi import FastAPI
from fastapi.responses import JSONResponse as FastAPIJSONResponse

from .ocs_utils import ocs_call
from .types import TConfig

T = TypeVar('T')


def not_none(value: T | None) -> TypeGuard[T]:
	return value is not None


def value_of(value: T, default: T | None = None) -> T | None:
	if value is None:
		return default

	if isinstance(value, str) and value.strip() == '':
		return default

	return value


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


def update_progress(app: FastAPI, progress: int):
	config: TConfig = app.extra['CONFIG']

	if config.disable_aaa:
		return

	try:
		ocs_call(
			method='PUT',
			path=f'/ocs/v1.php/apps/app_api/apps/status/{getenv("APP_ID")}',
			json_data={ 'progress': min(100, progress) },
			verify_ssl=config.httpx_verify_ssl,
		)
	except Exception as e:
		log_error(f'Error: Failed to update progress: {e}')


def exception_wrap(fun: Callable | None, *args, resconn: Connection, **kwargs):
	try:
		if fun is None:
			return resconn.send({ 'value': None, 'error': None })
		resconn.send({ 'value': fun(*args, **kwargs), 'error': None })
	except Exception as e:
		tb = traceback.format_exc()
		resconn.send({ 'value': None, 'error': e, 'traceback': tb })


def exec_in_proc(group=None, target=None, name=None, args=(), kwargs={}, *, daemon=None):  # noqa: B006
	pconn, cconn = mp.Pipe()
	kwargs['resconn'] = cconn
	p = mp.Process(
		group=group,
		target=partial(exception_wrap, target),
		name=name,
		args=args,
		kwargs=kwargs,
		daemon=daemon,
	)
	p.start()
	p.join()

	result = pconn.recv()
	if result['error'] is not None:
		print('original traceback:', result['traceback'], flush=True)
		raise result['error']

	return result['value']


def is_valid_source_id(source_id: str) -> bool:
	return re.match(r'^[a-zA-Z0-9_-]+__[a-zA-Z0-9_-]+: \d+$', source_id) is not None


def is_valid_provider_id(provider_id: str) -> bool:
	return re.match(r'^[a-zA-Z0-9_-]+__[a-zA-Z0-9_-]+$', provider_id) is not None


def timed(func: Callable):
	'''
	Decorator to time a function
	'''
	@wraps(func)
	def wrapper(*args, **kwargs):
		start = perf_counter_ns()
		res = func(*args, **kwargs)
		end = perf_counter_ns()
		print(f'{func.__name__} took {(end - start)/1e6:.2f}ms', flush=True)
		return res

	return wrapper
