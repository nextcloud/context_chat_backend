from importlib import import_module
from typing import Callable

from ..config import config

__all__ = ['load_model']


def _load_embedding_model(model_fn: Callable):
	from langchain.schema.embeddings import Embeddings

	if model_fn is None or not isinstance(model_fn, Embeddings):
		return None

	model = model_fn(
		**config.get("embedding", {}),
	)

	return model


def _load_llm_model(model_fn: Callable):
	from langchain.llms.base import LLM

	if model_fn is None or not isinstance(model_fn, LLM):
		return None

	model = model_fn(
		**config.get("llm", {}),
	)

	return model


def load_model(model_type: str, model_name: str):
	model = import_module(model_name)
	types = model.types

	if model_type not in types.keys():
		return None

	if model_type == "embedding":
		return _load_embedding_model(types.get("embedding", None))

	if model_type == "llm":
		return _load_llm_model(types.get("llm", None))

