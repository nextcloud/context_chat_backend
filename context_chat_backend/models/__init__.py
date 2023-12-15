from .load_model import load_model

_embedding_models = ['llama', 'hugging_face', 'instructor']
_llm_models = ['llama', 'hugging_face']

models = {
	'embedding': _embedding_models,
	'llm': _llm_models,
}

__all__ = ['init_model', 'models']


def init_model(model_type: str, model_info: tuple[str, dict]):
	'''
	Initializes a given model. This function assumes that the model is implemented in a module with
	the same name as the model in the models dir.
	'''
	model_name, _ = model_info
	available_models = models.get(model_type)

	if model_name not in available_models:
		raise AssertionError(f'Error: {model_type}_model should be one of {available_models}')

	model = load_model(model_type, model_info)

	if model is None:
		raise AssertionError(f'Error: {model_name} does not implement "{model_type}" type')

	return model
