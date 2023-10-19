from typing import Any
from langchain.vectorstores import VectorStore
from langchain.chains import LLMChain
from langchain import PromptTemplate
from langchain.llms import LLM

_LLM_TEMPLATE = """Answer based on this context and do not add any imaginative details:
{context}

{question}
"""


def process_query(vectordb: VectorStore, llm: LLM, query: str, limit: int = 5) -> Any | None:
	context_docs = vectordb.similarity_search(query, k=limit)

	print(f"Context docs: {context_docs}")

	context_text = " ".join(map(lambda d: d.page_content, context_docs))

	prompt = PromptTemplate(
		template=_LLM_TEMPLATE,
		input_variables=["context", "question"]
	)
	llm_chain = LLMChain(prompt=prompt, llm=llm)

	output = llm_chain.run(question=query, context=context_text)
	print(f'Output: {output}')

	return output

