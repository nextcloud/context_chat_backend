from typing import Any
from langchain.vectorstores import VectorStore
from langchain.llms.base import LLM

_LLM_TEMPLATE = """Answer based only on this context and do not add any imaginative details:
{context}

{question}
"""


def process_query(
		vectordb: VectorStore,
		llm: LLM,
		query: str,
		use_context: bool = True,
		limit: int = 5
	) -> Any | None:
	if not use_context:
		return llm.predict(query)

	context_docs = vectordb.similarity_search(query, k=limit)
	context_text = "\n".join(map(lambda d: d.page_content, context_docs))

	output = llm.predict(_LLM_TEMPLATE.format(context=context_text, question=query))
	return output
