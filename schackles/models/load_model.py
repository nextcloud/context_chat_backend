from importlib import import_module
from typing import Callable

from langchain.llms.base import LLM
from langchain.schema.embeddings import Embeddings
from ruamel.yaml import YAML

__all__ = ['load_model']

# this will raise an exception and is intended
with open('config.yaml') as f:
	try:
		yaml = YAML(typ='safe')
		config = yaml.load(f)
	except Exception as e:
		raise AssertionError("Error: could not load config.yaml") from e


def load_model(model_type: str, model_name: str) -> Embeddings | LLM | None:
	module = import_module(f".{model_name}", "schackles.models")

	if module is None or not hasattr(module, "get_model_for"):
		raise AssertionError(f"Error: could not load {model_name} model")

	get_model_for = module.get_model_for

	if not isinstance(get_model_for, Callable):
		return None

	return get_model_for(config.get(model_name, {}), model_type)
