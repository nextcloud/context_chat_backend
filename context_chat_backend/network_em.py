import httpx
from langchain_core.embeddings import Embeddings
from llama_cpp.llama_types import CreateEmbeddingResponse
from pydantic import BaseModel

from .config_parser import TConfig


class EmbeddingException(Exception):
	...


class NetworkEmbeddings(Embeddings, BaseModel):
	app_config: TConfig

	def _get_embedding(self, input_: str | list[str]) -> list[float] | list[list[float]]:
		emconf = self.app_config.embedding

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
