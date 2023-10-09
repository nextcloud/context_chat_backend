from importlib import import_module

from ....config import config

__all__ = ['load_model']


def _load_embedding_model(model_path: str):
	from langchain.embeddings import LlamaCppEmbeddings

	model = LlamaCppEmbeddings(
		model_path=model_path,
		**config.get("embedder", {})
	)

	return model


def _load_llm_model(model_path: str):
	from langchain.llms import LlamaCpp

	model = LlamaCpp(
		model_path=model_path,
		**config.get("llm", {})
	)

	return model


def load_model(model_type: str, model_path: str):
	model = import_module(f".{model_type}", __package__)
	types = model.types

	if model_type not in types:
		return None

	if model_type == 'embedding':
		return _load_embedding_model(model_path)

	if model_type == 'llm':
		return _load_llm_model(model_path)

