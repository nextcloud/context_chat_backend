from os import getenv, path

from langchain_community.embeddings.llamacpp import LlamaCppEmbeddings
from langchain_community.llms import LlamaCpp


def get_model_for(model_type: str, model_config: dict):
	model_dir = getenv('MODEL_DIR', 'persistent_storage/model_files')
	if str(model_config.get('model_path')).startswith('/'):
		model_dir = ''

	model_path = path.join(model_dir, model_config.get('model_path', ''))

	if model_config is None:
		return None

	if model_type == 'embedding':
		return LlamaCppEmbeddings(**{ **model_config, 'model_path': model_path })

	if model_type == 'llm':
		return LlamaCpp(**{ **model_config, 'model_path': model_path })

	return None
