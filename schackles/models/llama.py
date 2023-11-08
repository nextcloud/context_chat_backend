from langchain.embeddings import LlamaCppEmbeddings
from langchain.llms import LlamaCpp


def get_model_for(config: dict[str, dict], model_type: str):
	if (em_conf := config.get('embedding')) is not None and model_type == 'embedding':
		return LlamaCppEmbeddings(**em_conf)

	if (llm_conf := config.get('llm')) is not None and model_type == 'llm':
		return LlamaCpp(**llm_conf)

	return None
