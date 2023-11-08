from langchain.llms.base import LLM

from ..vectordb import BaseVectorDB

_LLM_TEMPLATE = """Answer based only on this context and do not add any imaginative details:
{context}

{question}
"""


def process_query(
	user_id: str,
	vectordb: BaseVectorDB,
	llm: LLM,
	query: str,
	use_context: bool = True,
	ctx_limit: int = 5
) -> str:
	if not use_context:
		return llm.predict(query)

	user_client = vectordb.get_user_client(user_id)
	if user_client is None:
		return llm.predict(query)

	context_docs = user_client.similarity_search(query, k=ctx_limit)
	context_text = "\n".join(map(lambda d: d.page_content, context_docs))

	output = llm.predict(_LLM_TEMPLATE.format(context=context_text, question=query))
	return output
