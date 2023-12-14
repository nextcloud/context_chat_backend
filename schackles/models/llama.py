from langchain.embeddings import LlamaCppEmbeddings
from langchain.llms.llamacpp import LlamaCpp


def get_model_for(model_type: str, model_config: dict):
	if model_config is None:
		return None

	if model_type == 'embedding':
		return LlamaCppEmbeddings(**model_config)

	if model_type == 'llm':
		return LlamaCpp(**model_config)

	return None
