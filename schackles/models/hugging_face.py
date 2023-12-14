from langchain.embeddings import HuggingFaceEmbeddings
from langchain.llms import HuggingFacePipeline


def get_model_for(model_type: str, model_config: dict):
	if model_config is None:
		return None

	if model_type == 'embedding':
		return HuggingFaceEmbeddings(**model_config)

	if model_type == 'llm':
		return HuggingFacePipeline.from_model_id(**model_config)

	return None
