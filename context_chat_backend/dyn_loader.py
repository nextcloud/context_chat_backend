import gc
from abc import ABC, abstractmethod
from time import time

import torch
from fastapi import FastAPI
from langchain.llms.base import LLM
from langchain.schema.embeddings import Embeddings

from .config_parser import TConfig
from .models import init_model
from .vectordb import get_vector_db
from .vectordb.base import BaseVectorDB, DbException

"""
app.extra params:
- EMBEDDING_MODEL: Embeddings
- VECTOR_DB: BaseVectorDB
- LLM_MODEL: LLM
- LLM_TEMPLATE: str
- LLM_NO_CTX_TEMPLATE: str
- LLM_END_SEPARATOR: str
- LLM_LAST_ACCESSED: timestamp
- EM_LAST_ACCESSED: timestamp
"""


class LoaderException(Exception):
	...


class Loader(ABC):
	def __init__(self, app: FastAPI, config: TConfig) -> None:
		self.app = app
		self.config = config

	@abstractmethod
	def load(self) -> BaseVectorDB | Embeddings | LLM:
		...

	@abstractmethod
	def offload(self):
		...


class VectorDBLoader(Loader):
	def load(self) -> BaseVectorDB:
		if self.app.extra.get('VECTOR_DB') is not None:
			return self.app.extra['VECTOR_DB']

		try:
			client_klass = get_vector_db(self.config['vectordb'][0])
		except (AssertionError, ImportError) as e:
			raise LoaderException() from e

		try:
			embedding_model = EmbeddingModelLoader(self.app, self.config).load()
			self.app.extra['VECTOR_DB'] = client_klass(embedding_model, **self.config['vectordb'][1])  # type: ignore
		except DbException as e:
			raise LoaderException() from e

		return self.app.extra['VECTOR_DB']

	def offload(self) -> None:
		if self.app.extra.get('VECTOR_DB') is not None:
			del self.app.extra['VECTOR_DB']
		gc.collect()


class EmbeddingModelLoader(Loader):
	def load(self) -> Embeddings:
		if self.app.extra.get('EMBEDDING_MODEL') is not None:
			self.app.extra['EM_LAST_ACCESSED'] = time()
			return self.app.extra['EMBEDDING_MODEL']

		try:
			model = init_model('embedding', self.config['embedding'])
		except AssertionError as e:
			raise LoaderException() from e

		if not isinstance(model, Embeddings):
			raise LoaderException(f'Error: {model} does not implement "embedding" type or has returned an invalid object')  # noqa: E501

		self.app.extra['EMBEDDING_MODEL'] = model
		self.app.extra['EM_LAST_ACCESSED'] = time()
		return model

	def offload(self) -> None:
		if self.app.extra.get('EMBEDDING_MODEL') is not None:
			del self.app.extra['EMBEDDING_MODEL']
		clear_cache()


class LLMModelLoader(Loader):
	def load(self) -> LLM:
		if self.app.extra.get('LLM_MODEL') is not None:
			self.app.extra['LLM_LAST_ACCESSED'] = time()
			return self.app.extra['LLM_MODEL']

		llm_name, llm_config = self.config['llm']
		self.app.extra['LLM_TEMPLATE'] = llm_config.pop('template', '')
		self.app.extra['LLM_NO_CTX_TEMPLATE'] = llm_config.pop('no_ctx_template', '')
		self.app.extra['LLM_END_SEPARATOR'] = llm_config.pop('end_separator', '')

		try:
			model = init_model('llm', (llm_name, llm_config))
		except AssertionError as e:
			raise LoaderException() from e
		if not isinstance(model, LLM):
			raise LoaderException(f'Error: {model} does not implement "llm" type or has returned an invalid object')

		self.app.extra['LLM_MODEL'] = model
		self.app.extra['LLM_LAST_ACCESSED'] = time()
		return model

	def offload(self) -> None:
		if self.app.extra.get('LLM_MODEL') is not None:
			del self.app.extra['LLM_MODEL']
		clear_cache()


def clear_gpu_cache() -> None:
	if torch.cuda.is_available() and torch.version.cuda:  # pyright: ignore [reportAttributeAccessIssue]
		torch.cuda.empty_cache()
		torch.cuda.ipc_collect()


def clear_cache() -> None:
	gc.collect()
	clear_gpu_cache()
