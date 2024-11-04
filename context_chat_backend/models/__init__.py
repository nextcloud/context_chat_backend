from collections.abc import Callable
from importlib import import_module

from langchain.llms.base import LLM
from langchain.schema.embeddings import Embeddings

_llm_models = ["nc_texttotext", "llama", "hugging_face", "ctransformer"]

models = {
    "llm": _llm_models,
}

__all__ = ["init_model", "load_model", "models", "LlmException"]


def load_model(model_type: str, model_info: tuple[str, dict]) -> Embeddings | LLM | None:
    model_name, model_config = model_info

    try:
        module = import_module(f".{model_name}", "context_chat_backend.models")
    except Exception as e:
        raise AssertionError(f"Error: could not load {model_name} model from context_chat_backend/models") from e

    if module is None or not hasattr(module, "get_model_for"):
        raise AssertionError(f"Error: could not load {model_name} model")

    get_model_for = module.get_model_for

    if not isinstance(get_model_for, Callable):
        raise AssertionError(f"Error: {model_name} does not have a valid loader function")

    return get_model_for(model_type, model_config)


def init_model(model_type: str, model_info: tuple[str, dict]):
    """
    Initializes a given model. This function assumes that the model is implemented in a module with
    the same name as the model in the models dir.
    """
    model_name, _ = model_info
    available_models = models.get(model_type, [])

    if model_name not in available_models:
        raise AssertionError(f"Error: {model_type}_model should be one of {available_models}")

    try:
        model = load_model(model_type, model_info)
    except Exception as e:
        raise AssertionError(f"Error: {model_name} failed to load") from e

    if model_type == "llm" and not isinstance(model, LLM):
        raise AssertionError(f'Error: {model} does not implement "llm" type or has returned an invalid object')

    return model


class LlmException(Exception): ...
