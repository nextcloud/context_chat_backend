#
# SPDX-FileCopyrightText: 2024 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
import logging
import socket
from time import sleep
from typing import Literal, TypedDict
from urllib.parse import urlparse

import niquests
from langchain_core.embeddings import Embeddings

from .types import (
	DocErrorEmbeddingException,
	EmbeddingException,
	FatalEmbeddingException,
	RetryableEmbeddingException,
	TConfig,
	TEmbeddingAuthApiKey,
	TEmbeddingAuthBasic,
)

logger = logging.getLogger('ccb.nextwork_em')
TCP_CONNECT_TIMEOUT = 2.0  # seconds

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


class NetworkEmbeddings(Embeddings):
	def __init__(self, app_config: TConfig):
		self.app_config = app_config

	def _get_host_and_port(self) -> tuple[str, int]:
		parsed = urlparse(self.app_config.embedding.base_url)
		host = parsed.hostname

		if not host:
			raise ValueError("Invalid URL: Missing hostname")

		if parsed.port:
			port = parsed.port
		else:
			port = 443 if parsed.scheme == "https" else 80

		return host, port

	def check_connection(self, check_origin: str) -> bool:
		try:
			host, port = self._get_host_and_port()
			sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
			sock.settimeout(TCP_CONNECT_TIMEOUT)
			sock.connect((host, port))
			sock.close()
			return True
		except (ValueError, TimeoutError, ConnectionRefusedError, socket.gaierror) as e:
			logger.warning(f'[{check_origin}] Embedding server is not reachable, retrying after some time: {e}')
			return False

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
					auth = None
				case TEmbeddingAuthApiKey(apikey=apikey):
					auth = niquests.auth.BearerTokenAuth(token=apikey)  # pyright: ignore[reportAttributeAccessIssue]
				case TEmbeddingAuthBasic(username=username, password=password):
					auth = niquests.auth.HTTPBasicAuth(username=username, password=password)  # pyright: ignore[reportAttributeAccessIssue]

			data = {'input': input_}
			if emconf.model_name:
				data['model'] = emconf.model_name

			response = niquests.post(
				f'{emconf.base_url.removesuffix("/")}/embeddings',
				json=data,
				timeout=emconf.request_timeout,
				auth=auth,
				verify=self.app_config.verify_ssl,
			)
			if response.status_code is None:
				raise EmbeddingException('Error: no response from embedding service')
			if response.status_code // 100 == 4:
				raise FatalEmbeddingException(
					response.text or f'Error: embedding request returned non-2xx status code {response.status_code}',
				)
			if response.status_code // 100 != 2:
				raise EmbeddingException(
					response.text or f'Error: embedding request returned non-2xx status code {response.status_code}',
					response,
				)
		except FatalEmbeddingException as e:
			logger.error('Fatal error while getting embeddings: %s', str(e), exc_info=e)
			raise e
		except EmbeddingException as e:
			try:
				if e.response:
					err_msg = e.response.json().get('error', {}).get('message', '')
					if err_msg == 'llama_decode returned -1':
						# the document coult not be processed
						raise DocErrorEmbeddingException(f'Failed to embed the document: {err_msg}') from e
			except niquests.exceptions.JSONDecodeError:
				...

			if try_ > 0:
				logger.debug('Retrying embedding request in 5 secs', extra={'try': try_})
				sleep(5)
				return self._get_embedding(input_, try_ - 1)
			raise RetryableEmbeddingException('Error: request to get embeddings failed') from e
		except niquests.exceptions.Timeout as e:
			if try_ > 0:
				logger.debug('Timeout while getting embeddings, retrying in 5 secs', extra={'try': try_})
				sleep(5)
				return self._get_embedding(input_, try_ - 1)
			logger.error('Timeout while getting embeddings', exc_info=e)
			raise EmbeddingException('Error: timeout while getting embeddings') from e
		except niquests.exceptions.ConnectionError as e:
			if self.app_config.embedding.workers > 0:
				logger.error(
					'Error connecting to the embedding server, check if it is running and the logs',
					exc_info=e,
				)
				raise EmbeddingException('Error: failed to connect to the embedding service') from e
			logger.error('Error connecting to the remote embedding service', exc_info=e)
			raise EmbeddingException('Error: failed to connect to the remote embedding service') from e
		except Exception as e:
			logger.error('Unexpected error while getting embeddings', exc_info=e)
			raise EmbeddingException('Error: unexpected error while getting embeddings') from e

		try:
			# converts TypedDict to a pydantic model
			resp = CreateEmbeddingResponse(**response.json())
			if isinstance(input_, str):
				return resp['data'][0]['embedding']
		except Exception as e:
			logger.error('Error parsing embedding response', exc_info=e)
			raise EmbeddingException('Error: failed to parse embedding response') from e

		# only one embedding in d['embedding'] since truncate is True
		return [d['embedding'] for d in resp['data']]  # pyright: ignore[reportReturnType]

	def embed_documents(self, texts: list[str]) -> list[list[float]]:
		batch_size = self.app_config.embedding.batch_size
		if batch_size <= 0 or len(texts) <= batch_size:
			return self._get_embedding(texts)  # pyright: ignore[reportReturnType]

		results: list[list[float]] = []
		for i in range(0, len(texts), batch_size):
			batch_embeddings = self._get_embedding(texts[i:i + batch_size])
			results.extend(batch_embeddings)  # pyright: ignore[reportArgumentType]
		return results

	def embed_query(self, text: str) -> list[float]:
		return self._get_embedding(text)  # pyright: ignore[reportReturnType]
