#
# SPDX-FileCopyrightText: 2023 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
import json
import logging
from base64 import b64decode, b64encode
from os import getenv

import httpx
from starlette.datastructures import URL, Headers
from starlette.responses import JSONResponse
from starlette.status import HTTP_401_UNAUTHORIZED
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger('ccb.ocs_utils')

def _sign_request(headers: dict, username: str = '') -> None:
	headers['EX-APP-ID'] = getenv('APP_ID')
	headers['EX-APP-VERSION'] = getenv('APP_VERSION')
	headers['OCS-APIRequest'] = 'true'
	headers['AUTHORIZATION-APP-API'] = b64encode(f'{username}:{getenv("APP_SECRET")}'.encode('UTF=8'))


# We assume that the env variables are set
def _verify_signature(headers: Headers) -> str | None:
	if headers.get('EX-APP-ID') is None or headers.get('EX-APP-ID') != getenv('APP_ID'):
		logger.error(f'Invalid EX-APP-ID:{headers.get("EX-APP-ID")} != {getenv("APP_ID")}')
		return None

	if headers.get('EX-APP-VERSION') is None or headers.get('EX-APP-VERSION') != getenv('APP_VERSION'):
		logger.error(
			f'Invalid EX-APP-VERSION:{headers.get("EX-APP-VERSION")} <=> {getenv("APP_VERSION")}'
		)
		return None

	if headers.get('AUTHORIZATION-APP-API') is None:
		logger.error('Missing AUTHORIZATION-APP-API header')
		return None

	auth_aa = b64decode(headers.get('AUTHORIZATION-APP-API', '')).decode('UTF-8', 'ignore')
	username, app_secret = auth_aa.split(':', maxsplit=1)

	if app_secret != getenv('APP_SECRET'):
		logger.error(f'Invalid APP_SECRET:{app_secret} != {getenv("APP_SECRET")}')
		return None

	return username


class AppAPIAuthMiddleware:
	'''
	Ensures the presence of AppAPI headers and verifies the app secret.
	It also adds the username to the scope (request.scope)
	'''
	def __init__(self, app: ASGIApp) -> None:
		self.app = app

	async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
		if scope['type'] != 'http':
			await self.app(scope, receive, send)
			return

		url = URL(scope=scope)
		if (url.path == '/heartbeat'):
			# no auth of /heartbeat
			await self.app(scope, receive, send)
			return

		headers = Headers(scope=scope)
		if (username := _verify_signature(headers)) is not None:
			scope['username'] = username
			await self.app(scope, receive, send)
			return

		error_response = JSONResponse(
			content={'error': 'Invalid signature of the request'},
			status_code=HTTP_401_UNAUTHORIZED,
		)
		await error_response(scope, receive, send)


def get_nc_url() -> str:
	return getenv('NEXTCLOUD_URL', '').removesuffix('/index.php').removesuffix('/')


def ocs_call(
	method: str,
	path: str,
	params: dict | None = None,
	json_data: dict | list | None = None,
	verify_ssl: bool = True,
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
	if params is None:
		params = {}

	params.update({'format': 'json'})
	headers = kwargs.pop('headers', {})
	data_bytes = None

	if json_data is not None:
		headers.update({'Content-Type': 'application/json'})
		data_bytes = json.dumps(json_data).encode('utf-8')

	_sign_request(headers, kwargs.get('username', ''))

	with httpx.Client(verify=verify_ssl) as client:
		ret = client.request(
			method=method.upper(),
			url=f'{get_nc_url()}/{path.removeprefix("/")}',
			params=params,
			content=data_bytes,
			headers=headers,
			**kwargs,
		)

		if ret.status_code // 100 != 2:
			logger.error(
				'ocs_call: %s %s failed with %d: %s',
				method.upper(), path, ret.status_code, ret.text,
			)
