from typing import Any
from langchain.vectorstores import VectorStore
from langchain.llms.base import LLM

_LLM_TEMPLATE = """Answer based on this context and do not add any imaginative details:
{context}

{question}
"""


def process_query(vectordb: VectorStore, llm: LLM, query: str, limit: int = 5) -> Any | None:
	context_docs = vectordb.similarity_search(query, k=limit)
	print(f"Context docs: {context_docs}")

	context_text = "\n".join(map(lambda d: d.page_content, context_docs))
	output = llm.predict(_LLM_TEMPLATE.format(context=context_text, question=query))
	print(f'Output: {output}')

	return output
