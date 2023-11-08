from langchain.embeddings import HuggingFaceEmbeddings
from langchain.llms import HuggingFacePipeline


def get_model_for(config: dict[str, dict], model_type: str):
	if (em_conf := config.get('embedding')) is not None and model_type == 'embedding':
		return HuggingFaceEmbeddings(**em_conf)

	if (llm_conf := config.get('llm')) is not None and model_type == 'llm':
		# return HuggingFacePipeline(**{**llm_conf, 'task': 'text2text-generation'})
		return HuggingFacePipeline(**llm_conf)

	return None
