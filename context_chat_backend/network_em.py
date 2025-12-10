#
# SPDX-FileCopyrightText: 2024 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
import logging
import os
from collections.abc import Generator
from time import sleep
from typing import Literal, TypedDict

import httpx
from langchain_core.embeddings import Embeddings
from pydantic import BaseModel

from .types import EmbeddingException, RetryableEmbeddingException, TConfig, TEmbeddingAuthApiKey, TEmbeddingAuthBasic
from .utils import value_of

logger = logging.getLogger('ccb.nextwork_em')

# Copied from llama_cpp/llama_types.py

class EmbeddingUsage(TypedDict):
	prompt_tokens: int
	total_tokens: int


class Embedding(TypedDict):
	index: int
	object: str
	embedding: list[float] | list[list[float]]


class CreateEmbeddingResponse(TypedDict):
	object: Literal["list"]
	model: str
	data: list[Embedding]
	usage: EmbeddingUsage


class ApiKeyAuth(httpx.Auth):
	def __init__(self, apikey: str | bytes) -> None:
		self._apikey = apikey

	def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
		request.headers['Authorization'] = f'Bearer {self._apikey}'
		yield request


class NetworkEmbeddings(Embeddings, BaseModel):
	app_config: TConfig

	def _get_embedding(self, input_: str | list[str], try_: int = 3) -> list[float] | list[list[float]]:
		emconf = self.app_config.embedding

		lengths = [len(text) for text in (input_ if isinstance(input_, list) else [input_])]
		logger.info(
			f'Sending embedding request for {len(lengths)} chunks of the following sizes (total: {sum(lengths)}):'
			, extra={'lengths':lengths}
		)

		try:
			match emconf.auth:
				case None:
					auth = httpx.USE_CLIENT_DEFAULT
				case TEmbeddingAuthApiKey(apikey=apikey):
					auth = ApiKeyAuth(apikey=apikey)
				case TEmbeddingAuthBasic(username=username, password=password):
					auth = httpx.BasicAuth(username=username, password=password)
				case 'from_env' if value_of('CCB_EM_APIKEY'):
					auth = ApiKeyAuth(apikey=os.environ['CCB_EM_APIKEY'])
				case 'from_env' if value_of('CCB_EM_USERNAME'):
					auth = httpx.BasicAuth(
						username=os.environ['CCB_EM_USERNAME'],
						password=os.environ['CCB_EM_PASSWORD'],
					)

			data = {'input': input_}
			if emconf.model:
				data['model'] = emconf.model

			with httpx.Client() as client:
				response = client.post(
					f'{emconf.base_url.removesuffix("/")}/embeddings',
					json=data,
					timeout=emconf.request_timeout,
					auth=auth,
				)
				if response.status_code != 200:
					raise EmbeddingException(response.text)
		except (
			EmbeddingException,
			httpx.RemoteProtocolError,
			httpx.ReadError,
			httpx.LocalProtocolError,
			httpx.PoolTimeout,
		) as e:
			if try_ > 0:
				logger.debug('Retrying embedding request in 5 secs', extra={'try': try_})
				sleep(5)
				return self._get_embedding(input_, try_ - 1)
			raise RetryableEmbeddingException('Error: request to get embeddings failed') from e
		except httpx.ConnectError as e:
			if self.app_config.embedding.workers > 0:
				logger.error(
					'Error connecting to the embedding server, check if it is running and the logs',
					exc_info=e,
				)
				raise EmbeddingException('Error: failed to connect to the embedding service') from e
			logger.error('Error connecting to the remote embedding service', exc_info=e)
			raise EmbeddingException('Error: failed to connect to the remote embedding service') from e
		except httpx.NetworkError as e:
			if try_ > 0:
				logger.debug('Network error while getting embeddings, retrying in 5 secs', extra={'try': try_})
				sleep(5)
				return self._get_embedding(input_, try_ - 1)
			logger.error('Network error while getting embeddings', exc_info=e)
			raise EmbeddingException('Error: network error while getting embeddings') from e
		except Exception as e:
			logger.error('Unexpected error while getting embeddings', exc_info=e)
			raise EmbeddingException('Error: unexpected error while getting embeddings') from e

		# converts TypedDict to a pydantic model
		resp = CreateEmbeddingResponse(**response.json())
		if isinstance(input_, str):
			return resp['data'][0]['embedding']

		# only one embedding in d['embedding'] since truncate is True
		return [d['embedding'] for d in resp['data']]  # pyright: ignore[reportReturnType]

	def embed_documents(self, texts: list[str]) -> list[list[float]]:
		return self._get_embedding(texts)  # pyright: ignore[reportReturnType]

	def embed_query(self, text: str) -> list[float]:
		return self._get_embedding(text)  # pyright: ignore[reportReturnType]
