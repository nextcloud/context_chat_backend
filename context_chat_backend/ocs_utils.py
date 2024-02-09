import json
from base64 import b64decode, b64encode
from logging import error as log_error
from os import getenv
from typing import Optional, Union

import httpx
from fastapi import Request, Response, responses
from starlette.datastructures import MutableHeaders
from starlette.middleware.base import (
	BaseHTTPMiddleware,
	RequestResponseEndpoint,
)


def _sign_request(headers: dict, username: str = '') -> None:
	headers['EX-APP-ID'] = getenv('APP_ID')
	headers['EX-APP-VERSION'] = getenv('APP_VERSION')
	headers['OCS-APIRequest'] = 'true'
	headers['AUTHORIZATION-APP-API'] = b64encode(f'{username}:{getenv("APP_SECRET")}'.encode('UTF=8'))


def _verify_signature(request: Request) -> str:
	# no auth of /heartbeat
	if request.url.path == '/heartbeat':
		return 'anon'

	# Header 'AA-VERSION' contains AppAPI version, for now it can be only one version,
	# so no handling of it.

	if request.headers.get('EX-APP-ID') != getenv('APP_ID'):
		log_error(f'Invalid EX-APP-ID:{request.headers.get("EX-APP-ID")} != {getenv("APP_ID")}')
		return None

	if request.headers.get('EX-APP-VERSION') != getenv('APP_VERSION'):
		log_error(
			f'Invalid EX-APP-VERSION:{request.headers.get("EX-APP-VERSION")} <=> {getenv("APP_VERSION")}'
		)
		return None

	auth_aa = b64decode(request.headers.get('AUTHORIZATION-APP-API')).decode('UTF-8')
	username, app_secret = auth_aa.split(':', maxsplit=1)

	if app_secret != getenv('APP_SECRET'):
		log_error(f'Invalid APP_SECRET:{app_secret} != {getenv("APP_SECRET")}')
		return None

	return username


class AppAPIAuthMiddleware(BaseHTTPMiddleware):
	'''
	Ensures the presence of AppAPI headers and verifies the app secret.
	It also adds the username to the request headers.
	'''
	async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
		if (username := _verify_signature(request)) is not None:
			new_headers = MutableHeaders(request.headers)
			new_headers['username'] = username

			request._headers = new_headers
			request.scope.update(headers=request.headers.raw)

			return await call_next(request)

		return responses.JSONResponse(
			content={'error': 'Invalid signature of the request'},
			status_code=401
		)


def get_nc_url() -> str:
	return getenv('NEXTCLOUD_URL').removesuffix('/index.php').removesuffix('/')


def ocs_call(
	method: str,
	path: str,
	params: Optional[dict] = {},
	json_data: Optional[Union[dict, list]] = None,
	**kwargs,
):
	'''
	Make a signed OCS network call to Nextcloud.

	Args
	----
	method: str
		The HTTP method to use.
	path: str
		The API path to call.
	params: Optional[dict]
		The query parameters to send.
	json_data: Optional[dict or list]
		The JSON data to send.
	kwargs: dict
		headers: dict
			Additional headers to send.
		username: str
			The username to use for signing the request.
		Additional keyword arguments to pass to the httpx.request function.
	'''
	if not params: params = {}

	params.update({'format': 'json'})
	headers = kwargs.pop('headers', {})
	data_bytes = None

	if json_data is not None:
		headers.update({'Content-Type': 'application/json'})
		data_bytes = json.dumps(json_data).encode('utf-8')

	_sign_request(headers, kwargs.get('username', ''))

	verify_ssl = getenv('HTTPX_VERIFY_SSL', '1').lower() == '1'

	return httpx.request(
		method=method.upper(),
		url=f'{get_nc_url()}/{path.removeprefix("/")}',
		params=params,
		content=data_bytes,
		headers=headers,
		# todo
		# verify=verify_ssl,
		verify=False,
		**kwargs,
	)
