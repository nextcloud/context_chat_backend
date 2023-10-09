import os
from importlib import import_module

from load_model import load_model

_embedding_models = ["llama", "hugging_face_small"]
# TODO: does huging_face_small work?
_llm_models = ["llama", "hugging_face_small"]

models = {
	"embedding": _embedding_models,
	"llm": _llm_models,
}

__all__ = ["init_model", "models"]


def init_model(model_type: str, model_name: str, model_path: str):
	"""
	Initializes a given model. This function assumes that the model is implemented in a module with
	the same name as the model in the models dir. This function will try to import the module and
	call the load_model function from it. The load_model function should return the model object if
	the model was loaded successfully, otherwise it should return None.
	"""
	available_models = models.get(model_type)

	if model_name not in available_models:
		raise AssertionError(f"Error: {model_type}_model should be one of {available_models}")

	# TODO: error handling?
	return load_model(model_type, model_name, model_path)

	# init_fn = __import__(".llama.load_model", fromlist=[None])
	model = import_module(model_name)

	if init_fn is None:
		raise AssertionError(f"Error: could not load {model_name}")

	if not isinstance(model_path, str) or not os.path.exists(model_path):
		raise AssertionError(f"Error: \"{model_path}\" is not a valid path for {model_name} model")

	model = init_fn(model_type, model_path)

	if model is None:
		raise AssertionError(f"Error: {model_name} does not implement \"{model_type}\" type")

	return model

