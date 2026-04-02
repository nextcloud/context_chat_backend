#
# SPDX-FileCopyrightText: 2023 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
import io
import logging
import multiprocessing as mp
import os
import sys
import traceback
from collections.abc import Callable
from functools import partial, wraps
from multiprocessing.connection import Connection
from time import perf_counter_ns
from typing import Any, TypeGuard, TypeVar

from fastapi.responses import JSONResponse as FastAPIJSONResponse

from .types import AppRole, TConfig, TEmbeddingAuthApiKey, TEmbeddingAuthBasic, TEmbeddingConfig

T = TypeVar('T')
_logger = logging.getLogger('ccb.utils')


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
			_logger.error(f'Failed request ({status_code}): {content}')
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


class SubprocessKilledError(RuntimeError):
	"""Raised when a subprocess exits with a non-zero exit code (likely OOM kill or unhandled signal)."""

	def __init__(self, pid: int, target_name: str, exitcode: int):
		super().__init__(
			f'Subprocess PID {pid} for {target_name} exited with non-zero exit code {exitcode}'
			' — possible OOM kill or unhandled signal'
		)
		self.exitcode = exitcode


def exception_wrap(fun: Callable | None, *args, resconn: Connection, stdconn: Connection, **kwargs):
	stdout_capture = io.StringIO()
	stderr_capture = io.StringIO()
	sys.stdout = stdout_capture
	sys.stderr = stderr_capture

	try:
		if fun is None:
			return resconn.send({ 'value': None, 'error': None })
		resconn.send({ 'value': fun(*args, **kwargs), 'error': None })
	except BaseException as e:
		tb = traceback.format_exc()
		resconn.send({ 'value': None, 'error': e, 'traceback': tb })
	finally:
		stdconn.send({'stdout': stdout_capture.getvalue(), 'stderr': stderr_capture.getvalue()})


def exec_in_proc(group=None, target=None, name=None, args=(), kwargs={}, *, daemon=None):  # noqa: B006
	pconn, cconn = mp.Pipe()
	std_pconn, std_cconn = mp.Pipe()
	kwargs['resconn'] = cconn
	kwargs['stdconn'] = std_cconn
	p = mp.Process(
		group=group,
		target=partial(exception_wrap, target),
		name=name,
		args=args,
		kwargs=kwargs,
		daemon=daemon,
	)
	target_name = getattr(target, '__name__', str(target))
	_logger.debug('Starting subprocess for %s', target_name)
	start = perf_counter_ns()
	p.start()
	_logger.debug('Subprocess PID %d started for %s, waiting for it to finish (no timeout)', p.pid, target_name)
	p.join()
	elapsed_ms = (perf_counter_ns() - start) / 1e6
	_logger.debug(
		'Subprocess PID %d for %s finished in %.2f ms (exit code: %s)',
		p.pid, target_name, elapsed_ms, p.exitcode,
	)
	stdobj = std_pconn.recv()
	_logger.info(f'std info for {target_name}', extra={
		'stdout': stdobj['stdout'],
		'stderr': stdobj['stderr'],
	})

	result = pconn.recv()
	if result['error'] is not None:
		_logger.error('original traceback: %s', result['traceback'])
		raise result['error']

	if p.exitcode != 0:
		_logger.warning(
			'Subprocess PID %d for %s exited with non-zero exit code %d after %.2f ms'
			' — possible OOM kill or unhandled signal',
			p.pid, target_name, p.exitcode, elapsed_ms,
		)
		raise SubprocessKilledError(p.pid or 0, target_name, p.exitcode or -1)

	return result['value']


def timed(func: Callable):
	'''
	Decorator to time a function
	'''
	@wraps(func)
	def wrapper(*args, **kwargs):
		start = perf_counter_ns()
		res = func(*args, **kwargs)
		end = perf_counter_ns()
		_logger.debug(f'{func.__name__} took {(end - start)/1e6:.2f}ms')
		return res

	return wrapper


def redact_config(config: TConfig | TEmbeddingConfig) -> TConfig | TEmbeddingConfig:
	'''
	Redact sensitive information from the config for logging
	'''
	config_copy = config.model_copy(deep=True)

	if isinstance(config_copy, TConfig):
		em_conf = config_copy.embedding
	else:
		em_conf = config_copy

	if em_conf.auth:
		if isinstance(em_conf.auth, TEmbeddingAuthApiKey):
			em_conf.auth.apikey = '***REDACTED***'
		elif isinstance(em_conf.auth, TEmbeddingAuthBasic):
			em_conf.auth.username = '***REDACTED***'
			em_conf.auth.password = '***REDACTED***'  # noqa: S105

	return config_copy


def get_app_role() -> AppRole:
	role = os.getenv('APP_ROLE', '').lower()
	if role == '':
		return AppRole.NORMAL
	if role not in ['indexing', 'rp']:
		_logger.warning(f'Invalid app role: {role}, defaulting to all roles')
		return AppRole.NORMAL
	return AppRole(role)
