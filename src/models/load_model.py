# import importlib.util as importutil
# import sys
from langchain.schema.embeddings import Embeddings
from langchain.llms.base import LLM

__all__ = ['load_model']


def load_model(model_type: str, model_name: str) -> Embeddings | LLM | None:
	# TODO
	# module_name = model_name + "_local"
	# file_path = f"src/models/{model_name}.py"
	# spec = importutil.spec_from_file_location(module_name, file_path)
	# module = importutil.module_from_spec(spec)
	# sys.modules[module_name] = module

	# if module is None or not hasattr(module, "types"):
	# 	raise AssertionError(f"Error: could not load {model_name} model")

	if model_name == "llama":
		from .llama import types
	elif model_name == "hugging_face_small":
		from .hugging_face_small import types

	if not isinstance(types, dict) or model_type not in types.keys():
		return None

	if model_type == "embedding":
		return types.get("embedding", None)

	if model_type == "llm":
		return types.get("llm", None)

