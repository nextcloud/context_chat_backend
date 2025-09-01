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

def sign_request(headers: dict, username: str = '') -> None:
	headers['EX-APP-ID'] = getenv('APP_ID')
	headers['EX-APP-VERSION'] = getenv('APP_VERSION')
	headers['OCS-APIRequest'] = 'true'
	headers['AUTHORIZATION-APP-API'] = b64encode(f'{username}:{getenv("APP_SECRET")}'.encode('UTF=8'))


# We assume that the env variables are set
def _verify_signature(headers: Headers) -> tuple[str | None, str | None]:
        if headers.get('EX-APP-ID') is None or headers.get('EX-APP-ID') != getenv('APP_ID'):
                err = f'Invalid EX-APP-ID received: "{headers.get("EX-APP-ID")}", expected "{getenv("APP_ID")}"'
                logger.error(err)
                return None, err

        if headers.get('EX-APP-VERSION') is None or headers.get('EX-APP-VERSION') != getenv('APP_VERSION'):
                err = (
                        'Invalid EX-APP-VERSION received: '
                        f'"{headers.get("EX-APP-VERSION")}", expected '
                        f'"{getenv("APP_VERSION")}". '
                        'A reinstall of the app context_chat_backend in app_api '
                        'keeping the data can potentially fix it.'
                )
                logger.error(err)
                return None, err

        if headers.get('AUTHORIZATION-APP-API') is None:
                err = 'Missing AUTHORIZATION-APP-API header'
                logger.error(err)
                return None, err

        auth_aa = b64decode(headers.get('AUTHORIZATION-APP-API', '')).decode('UTF-8', 'ignore')
        username, app_secret = auth_aa.split(':', maxsplit=1)

        if app_secret != getenv('APP_SECRET'):
                err = 'Invalid APP_SECRET received'
                logger.error(err)
                return None, err

        return username, None


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

                headers = Headers(scope=scope)
                username, err = _verify_signature(headers)
                if err is None and username is not None:
                        scope['username'] = username
                        await self.app(scope, receive, send)
                        return

                error_response = JSONResponse(
                        content={'error': err or 'Invalid signature of the request'},
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

	sign_request(headers, kwargs.get('username', ''))

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
