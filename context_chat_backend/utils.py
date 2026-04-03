#
# SPDX-FileCopyrightText: 2023 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
import atexit
import faulthandler
import io
import logging
import multiprocessing as mp
import os
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

	def __init__(self, pid: int, target_name: str, exitcode: int):
		super().__init__(
			f'Subprocess PID {pid} for {target_name} exited with signal {abs(exitcode)} '
			f'(raw exit code: {exitcode})'
		)
		self.exitcode = exitcode


class SubprocessExecutionError(RuntimeError):
	"""Raised when a subprocess exits non-zero without a recoverable Python exception payload."""

	def __init__(self, pid: int, target_name: str, exitcode: int, details: str = ''):
		msg = f'Subprocess PID {pid} for {target_name} exited with non-zero exit code {exitcode}'
		if details:
			msg = f'{msg}: {details}'
		super().__init__(msg)
		self.exitcode = exitcode


_MAX_STD_CAPTURE_CHARS = 64 * 1024


def _truncate_capture(text: str) -> tuple[str, bool]:
	if len(text) <= _MAX_STD_CAPTURE_CHARS:
		return text, False

	head = _MAX_STD_CAPTURE_CHARS // 2
	tail = _MAX_STD_CAPTURE_CHARS - head
	omitted = len(text) - _MAX_STD_CAPTURE_CHARS
	truncated = (
		f'[truncated {omitted} chars]\n'
		f'{text[:head]}\n'
		'[...snip...]\n'
		f'{text[-tail:]}'
	)
	return truncated, True


def exception_wrap(fun: Callable | None, *args, resconn: Connection, stdconn: Connection, **kwargs):
	# --- diagnostic probes: write directly to the real stderr FD so they survive
	# Python's stdout/stderr redirection below and even os._exit() won't hide them
	# from the parent process's stderr stream.
	_diag_fd = os.dup(2)  # dup before we capture sys.stderr

	def _raw_diag(msg: str) -> None:
		with suppress(Exception):
			os.write(_diag_fd, (msg + '\n').encode())

	# Enable faulthandler on the real FD so crash tracebacks (SIGSEGV etc.) appear.
	with suppress(Exception):
		faulthandler.enable(file=os.fdopen(os.dup(_diag_fd), 'w', closefd=True), all_threads=True)

	# Atexit probe: if this message NEVER appears, it means os._exit() (C-level)
	# was called with Python's cleanup phase entirely skipped.
	_fun_name = getattr(fun, '__name__', str(fun))
	atexit.register(
		_raw_diag,
		f'[exception_wrap/atexit] pid={os.getpid()} target={_fun_name}'
		': Python atexit reached (normal Python exit)',
	)

	stdout_capture = io.StringIO()
	stderr_capture = io.StringIO()
	orig_stdout = sys.stdout
	orig_stderr = sys.stderr
	sys.stdout = stdout_capture
	sys.stderr = stderr_capture

	try:
		if fun is None:
			resconn.send({ 'value': None, 'error': None })
			_raw_diag(f'[exception_wrap/probe] pid={os.getpid()} target={_fun_name}: result sent (fun=None)')
		else:
			result_value = fun(*args, **kwargs)
			_raw_diag(f'[exception_wrap/probe] pid={os.getpid()} target={_fun_name}: fun() returned, sending result')
			resconn.send({ 'value': result_value, 'error': None })
			_raw_diag(f'[exception_wrap/probe] pid={os.getpid()} target={_fun_name}: result pipe send complete')
	except BaseException as e:
		tb = traceback.format_exc()
		_raw_diag(
			f'[exception_wrap/probe] pid={os.getpid()} target={_fun_name}'
			f': caught {type(e).__name__}: {e}'
		)
		payload = {
			'value': None,
			'error': e,
			'traceback': tb,
			'error_type': type(e).__name__,
			'error_module': type(e).__module__,
			'error_message': str(e),
		}
		try:
			resconn.send(payload)
		except Exception as send_err:
			# Fallback for unpicklable exceptions.
			with suppress(Exception):
				resconn.send({
					'value': None,
					'error': None,
					'traceback': tb,
					'error_type': type(e).__name__,
					'error_module': type(e).__module__,
					'error_message': str(e),
					'send_error': str(send_err),
				})
	finally:
		sys.stdout = orig_stdout
		sys.stderr = orig_stderr
		stdout_text, stdout_truncated = _truncate_capture(stdout_capture.getvalue())
		stderr_text, stderr_truncated = _truncate_capture(stderr_capture.getvalue())
		with suppress(Exception):
			stdconn.send({
				'stdout': stdout_text,
				'stderr': stderr_text,
				'stdout_truncated': stdout_truncated,
				'stderr_truncated': stderr_truncated,
			})
		_raw_diag(f'[exception_wrap/probe] pid={os.getpid()} target={_fun_name}: finally block complete')
		with suppress(Exception):
			os.close(_diag_fd)


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

	result = None
	stdobj = {
		'stdout': '',
		'stderr': '',
		'stdout_truncated': False,
		'stderr_truncated': False,
	}
	got_result = False
	got_std = False

	# Drain result/std pipes while child is still alive to avoid deadlock on full pipe buffers.
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
				got_std = True
	if stdobj['stdout'] or stdobj['stderr']:
		extra = {
			'stdout': stdobj['stdout'],
			'stderr': stdobj['stderr'],
		}
		if stdobj.get('stdout_truncated') or stdobj.get('stderr_truncated'):
			extra['stdio_truncated'] = {
				'stdout': bool(stdobj.get('stdout_truncated')),
				'stderr': bool(stdobj.get('stderr_truncated')),
			}
		_logger.info('std info for %s', target_name, extra=extra)

	if not got_result:
		with suppress(EOFError, OSError, BrokenPipeError):
			if pconn.poll():
				result = pconn.recv()
				got_result = True

	if result is not None and result.get('error') is not None:
		_logger.error('original traceback: %s', result.get('traceback', ''))
		raise result['error']

	if result is not None and result.get('error_type'):
		details = (
			f"{result.get('error_module', '')}.{result.get('error_type', '')}: "
			f"{result.get('error_message', '')}"
		)
		if result.get('traceback'):
			_logger.error('remote traceback: %s', result['traceback'])
		raise SubprocessExecutionError(p.pid or 0, target_name, p.exitcode or 1, details)

	if p.exitcode and p.exitcode < 0:
		_logger.warning(
			'Subprocess PID %d for %s exited due to signal %d after %.2f ms',
			p.pid, target_name, abs(p.exitcode), elapsed_ms,
		)
		raise SubprocessKilledError(p.pid or 0, target_name, p.exitcode)

	if p.exitcode not in (None, 0):
		raise SubprocessExecutionError(
			p.pid or 0,
			target_name,
			p.exitcode,
			'No structured exception payload received from child process',
		)

	if result is None:
		raise SubprocessExecutionError(
			p.pid or 0,
			target_name,
			0,
			'Subprocess exited successfully but returned no result payload',
		)

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
