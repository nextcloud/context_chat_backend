#
# SPDX-FileCopyrightText: 2024 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
import logging
from typing import Literal, TypedDict

import httpx
from langchain_core.embeddings import Embeddings
from pydantic import BaseModel

from .types import EmbeddingException, TConfig

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


class NetworkEmbeddings(Embeddings, BaseModel):
	app_config: TConfig

	def _get_embedding(self, input_: str | list[str]) -> list[float] | list[list[float]]:
		emconf = self.app_config.embedding

		lengths = [len(text) for text in (input_ if isinstance(input_, list) else [input_])]
		logger.info(f'Sending embedding request for {len(lengths)} chunks of the following sizes: ', lengths)

		try:
			with httpx.Client() as client:
				response = client.post(
					f'{emconf.protocol}://{emconf.host}:{emconf.port}/v1/embeddings',
					json={'input': input_},
					timeout=emconf.request_timeout,
				)
		except Exception as e:
			raise EmbeddingException('Error: request to get embeddings failed') from e

		try:
			response.raise_for_status()
		except Exception as e:
			raise EmbeddingException(f'Error: failed to get embeddings: {response.text}') from e

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
