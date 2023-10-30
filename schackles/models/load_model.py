from importlib import import_module
from langchain.schema.embeddings import Embeddings
from langchain.llms.base import LLM

__all__ = ['load_model']


def load_model(model_type: str, model_name: str) -> Embeddings | LLM | None:
	module = import_module(f".{model_name}", "schackles.models")

	if module is None or not hasattr(module, "types"):
		raise AssertionError(f"Error: could not load {model_name} model")

	types = module.types

	if not isinstance(types, dict) or model_type not in types.keys():
		return None

	if model_type == "embedding":
		return types.get("embedding", None)

	if model_type == "llm":
		return types.get("llm", None)

