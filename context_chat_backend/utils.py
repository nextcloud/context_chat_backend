#
# SPDX-FileCopyrightText: 2023 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
import faulthandler
import io
import logging
import multiprocessing as mp
import os
import signal
import sys
import traceback
from collections.abc import Callable
from contextlib import suppress
from functools import partial, wraps
from multiprocessing.connection import Connection
from time import perf_counter_ns
from typing import Any, TypeGuard, TypeVar

from fastapi.responses import JSONResponse as FastAPIJSONResponse

from .types import AppRole, TConfig, TEmbeddingAuthApiKey, TEmbeddingAuthBasic, TEmbeddingConfig

T = TypeVar('T')
_logger = logging.getLogger('ccb.utils')
_MAX_STD_CAPTURE_CHARS = 64 * 1024


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
	"""Raised when a subprocess is terminated by a signal (for example SIGKILL)."""

	def __init__(self, pid: int | None, target_name: str, exitcode: int):
		super().__init__(
			f'Subprocess PID {pid} for {target_name} exited with signal {abs(exitcode)} '
			f'(raw exit code: {exitcode})'
		)
		self.exitcode = exitcode


class SubprocessExecutionError(RuntimeError):
	"""Raised when a subprocess exits without a recoverable Python exception payload."""

	def __init__(self, pid: int | None, target_name: str, exitcode: int, details: str = ''):
		msg = f'Subprocess PID {pid} for {target_name} exited with exit code {exitcode}'
		if details:
			msg = f'{msg}: {details}'
		super().__init__(msg)
		self.exitcode = exitcode


def _truncate_capture(text: str) -> str:
	if len(text) <= _MAX_STD_CAPTURE_CHARS:
		return text

	head = _MAX_STD_CAPTURE_CHARS // 2
	tail = _MAX_STD_CAPTURE_CHARS - head
	omitted = len(text) - _MAX_STD_CAPTURE_CHARS
	return (
		f'[truncated {omitted} chars]\n'
		f'{text[:head]}\n'
		'[...snip...]\n'
		f'{text[-tail:]}'
	)


def exception_wrap(fun: Callable | None, *args, resconn: Connection, stdconn: Connection, **kwargs):
	# ignore SIGINT and SIGTERM in child processes these signals don't immediately stop these processes
	# the handling is done in the fastapi lifetime to do a graceful shutdown
	# SIGKILL is not ignored
	signal.signal(signal.SIGINT, signal.SIG_IGN)
	signal.signal(signal.SIGTERM, signal.SIG_IGN)

	# Preserve real stderr FD for faulthandler before we redirect sys.stderr.
	_faulthandler_fd = os.dup(2)
	with suppress(Exception):
		faulthandler.enable(
			file=os.fdopen(_faulthandler_fd, 'w', closefd=False),
			all_threads=True,
		)

	stdout_capture = io.StringIO()
	stderr_capture = io.StringIO()
	orig_stdout = sys.stdout
	orig_stderr = sys.stderr
	sys.stdout = stdout_capture
	sys.stderr = stderr_capture

	try:
		value = None if fun is None else fun(*args, **kwargs)
		try:
			resconn.send({ 'value': value, 'error': None })
		except (BrokenPipeError, OSError, EOFError):
			...  # parent closed the pipe during shutdown, exit cleanly
	except BaseException as e:
		tb = traceback.format_exc()
		payload = {
			'value': None,
			'error': e,
			'traceback': tb,
		}
		try:
			resconn.send(payload)
		except Exception as send_err:
			stderr_capture.write(f'Original error: {e}, pipe send error: {send_err}')
	finally:
		sys.stdout = orig_stdout
		sys.stderr = orig_stderr
		stdout_text = _truncate_capture(stdout_capture.getvalue())
		stderr_text = _truncate_capture(stderr_capture.getvalue())
		with suppress(Exception):
			stdconn.send({
				'stdout': stdout_text,
				'stderr': stderr_text,
			})
		with suppress(Exception):
			os.close(_faulthandler_fd)


def exec_in_proc(group=None, target=None, name=None, args=(), kwargs=None, *, daemon=None):
	if not kwargs:
		kwargs = {}

	# parent, child
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
	start = perf_counter_ns()
	p.start()
	_logger.debug('Subprocess PID %d started for %s', p.pid, target_name)

	result = None
	stdobj = { 'stdout': '', 'stderr': '' }
	got_result = False
	got_std = False

	# Drain result/std pipes while child is still alive to avoid deadlock on full pipe buffers.
	# Pipe's buffer size is 64 KiB
	while p.is_alive() and (not got_result or not got_std):
		if not got_result and pconn.poll(0.1):
			with suppress(EOFError, OSError, BrokenPipeError):
				result = pconn.recv()
				got_result = True
		if not got_std and std_pconn.poll():
			with suppress(EOFError, OSError, BrokenPipeError):
				stdobj = std_pconn.recv()
				got_std = True

	p.join()
	elapsed_ms = (perf_counter_ns() - start) / 1e6
	_logger.debug(
		'Subprocess PID %d for %s finished in %.2f ms (exit code: %s)',
		p.pid, target_name, elapsed_ms, p.exitcode,
	)

	if not got_std:
		with suppress(EOFError, OSError, BrokenPipeError):
			if std_pconn.poll():
				stdobj = std_pconn.recv()
				# no need to update got_std here
	if stdobj.get('stdout') or stdobj.get('stderr'):
		_logger.info('std info for %s', target_name, extra={
			'stdout': stdobj.get('stdout', ''),
			'stderr': stdobj.get('stderr', ''),
		})

	if not got_result:
		with suppress(EOFError, OSError, BrokenPipeError):
			if pconn.poll():
				result = pconn.recv()
				# no need to update got_result here

	if result is not None and result.get('error') is not None:
		_logger.error(
			'original traceback of %s (PID %d, exitcode: %s): %s',
			target_name,
			p.pid,
			p.exitcode,
			result.get('traceback', ''),
		)
		raise result['error']

	if result is not None and 'value' in result:
		if p.exitcode not in (None, 0):
			_logger.warning(
				'Subprocess PID %d for %s exited with code %s after %.2f ms'
				' but returned a valid result',
				p.pid, target_name, p.exitcode, elapsed_ms,
			)
		return result['value']

	if p.exitcode and p.exitcode < 0:
		_logger.warning(
			'Subprocess PID %d for %s exited due to signal %d, exitcode %d after %.2f ms',
			p.pid, target_name, abs(p.exitcode), p.exitcode, elapsed_ms,
		)
		raise SubprocessKilledError(p.pid, target_name, p.exitcode)

	if p.exitcode not in (None, 0):
		raise SubprocessExecutionError(
			p.pid,
			target_name,
			p.exitcode,
			f'No structured exception payload received from child process: {result}',
		)

	raise SubprocessExecutionError(
		p.pid,
		target_name,
		0,
		f'Subprocess exited successfully but returned no result payload: {result}',
	)


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
	if role not in ['indexing', 'rp', 'up']:
		_logger.warning(f'Invalid app role: {role}, defaulting to all roles')
		return AppRole.NORMAL
	return AppRole(role)


def is_k8s_env():
	role = get_app_role()
	return role != AppRole.NORMAL
