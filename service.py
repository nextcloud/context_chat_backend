from typing import Any, Iterator, List
from werkzeug.datastructures.file_storage import FileStorage
from flask import Response
# from langchain.llms import HuggingFacePipeline
from langchain.llms import LlamaCpp
from langchain.chains import LLMChain
from langchain.agents import initialize_agent, Tool, AgentType
from langchain.utilities import GoogleSerperAPIWrapper
from langchain import PromptTemplate

from vectordb import (
	embed_files,
	embed_texts,
	get_similar_documents,
	setup_schema,
	delete_files,
)
from utils import CLASS_NAME

_ALLOWED_MIME_TYPES = [
	'text/plain',
	'text/markdown',
	'application/json',
]

_LLM_MODEL_PATH = "./models/codellama-7b.Q5_K_M.gguf"
_LLM_CONTEXT_LENGTH = 2048
_LLM_TEMPLATE = """Answer based on this context and do not add imaginative details:
{context}

{question}
"""

# llm
prompt = PromptTemplate(template=_LLM_TEMPLATE, input_variables=[
						"context", "question"])
# TODO:
llm = LlamaCpp(model_path=_LLM_MODEL_PATH, n_ctx=_LLM_CONTEXT_LENGTH)


def _allowed_file(file: FileStorage) -> bool:
	return file.headers \
		.get('type', type=str, default='') \
		.split('mimetype: ') \
		.pop() in _ALLOWED_MIME_TYPES

# we won't have this in the future maybe because we would need metadata attached to the file/data
# and thus everything would be data with metadata then


def process_files(user_id: str, filesIter: Iterator[FileStorage]) -> List[str]:
	return embed_files(user_id, filter(_allowed_file, filesIter))


def process_texts(user_id: str, texts: List[dict]) -> List[str]:
	return embed_texts(user_id, texts)


def get_similar_docs(user_id: str, query: str, limit: int = 5) -> Response:
	return get_similar_documents(user_id, query, limit)


def delete_files_from_db(user_id: str, filenames: List[str]) -> Response:
	return delete_files(user_id, filenames)


def process_query(user_id: str, query: str, limit: int = 5) -> Any | None:
	setup_schema(user_id)

	context_docs = get_similar_documents(user_id, query, limit)

	print(f"User({user_id}), Query: {query}")
	print(f"Context docs: {context_docs}")

	try:
		docs: List[dict] = context_docs['data']['Get'][CLASS_NAME(user_id)]

		context_text = " ".join(map(lambda d: d['text'], docs))

		llm_chain = LLMChain(prompt=prompt, llm=llm)
		output = llm_chain.run(question=query, context=context_text)

		print(f'Output: {output}')
		return output
	except KeyError:
		return None

	# TODO: ? callback_manager = CallbackManager([StreamingStdOutCallbackHandler()])


search = GoogleSerperAPIWrapper()
tools = [
	Tool(
		name="Intermediate Answer",
		func=search.run,
		description="useful for when you need to ask with search",
	)
]


def process_search_query(query: str):
	print(f"Search Query: {query}")

	self_ask_with_search = initialize_agent(
		tools, llm, agent=AgentType.SELF_ASK_WITH_SEARCH, verbose=True
	)
	output = self_ask_with_search.run(query)

	print(f"Final output: {output}")
	return output

