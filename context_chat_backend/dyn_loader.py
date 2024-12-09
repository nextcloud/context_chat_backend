#ruff: noqa: I001
#
# SPDX-FileCopyrightText: 2024 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#

import gc
import multiprocessing as mp
import os
import signal
import subprocess
from abc import ABC, abstractmethod
from time import sleep, time
from typing import Any

import httpx
import psutil
import torch
from fastapi import FastAPI
from langchain.llms.base import LLM

from .models.loader import init_model
from .network_em import NetworkEmbeddings
from .types import LoaderException, TConfig
from .vectordb.base import BaseVectorDB
from .vectordb.loader import get_vector_db
from .vectordb.types import DbException


class Loader(ABC):
	@abstractmethod
	def load(self) -> Any:
		...

	@abstractmethod
	def offload(self):
		...

pid = mp.Value('i', 0)

class EmbeddingModelLoader(Loader):
	def __init__(self, config: TConfig):
		self.config = config
		# todo: temp measure
		self.logfile = open('embedding_model.log', 'a+')

	def load(self):
		global pid

		emconf = self.config.embedding

		# start the embedding server if workers are > 0
		if emconf.workers > 0:
			# compare with None, as PID can be 0, you never know
			if pid.value > 0 and psutil.pid_exists(pid.value):
				return

			proc = subprocess.Popen(
				['./main_em.py'],
				stdout=self.logfile,
				stderr=self.logfile,
				stdin=None,
				close_fds=True,
				env=os.environ,
			)
			pid.value = proc.pid

		# poll for heartbeat
		try_ = 0
		while try_ < 20:
			with httpx.Client() as client:
				try:
					# test the server is up
					response = client.post(
						f'{emconf.protocol}://{emconf.host}:{emconf.port}/v1/embeddings',
						json={'input': 'hello'},
						timeout=20, # seconds
					)
					if response.status_code == 200:
						return
				except Exception:
					print(f'Try {try_} failed in exception')
				try_ += 1
				sleep(3)

		print('Error: failed to start the embedding server', flush=True)
		os.kill(os.getpid(), signal.SIGTERM)

	def offload(self):
		global pid
		if pid.value > 0 and psutil.pid_exists(pid.value):
			os.kill(pid.value, signal.SIGTERM)
		self.logfile.close()


class VectorDBLoader(Loader):
	def __init__(self, em_loader: EmbeddingModelLoader, config: TConfig) -> None:
		self.config = config
		self.em_loader = em_loader

	def load(self) -> BaseVectorDB:
		try:
			client_klass = get_vector_db(self.config.vectordb[0])
		except (AssertionError, ImportError) as e:
			raise LoaderException() from e

		try:
			self.em_loader.load()
			embedding_model = NetworkEmbeddings(app_config=self.config)
			return client_klass(embedding_model, **self.config.vectordb[1])  # type: ignore
		except DbException as e:
			raise LoaderException() from e

	def offload(self) -> None:
		self.em_loader.offload()
		clear_cache()


class LLMModelLoader(Loader):
	def __init__(self, app: FastAPI, config: TConfig) -> None:
		self.config = config
		self.app = app

	def load(self) -> LLM:
		if self.app.extra.get('LLM_MODEL') is not None:
			self.app.extra['LLM_LAST_ACCESSED'] = time()
			return self.app.extra['LLM_MODEL']

		llm_name, llm_config = self.config.llm
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
