from langchain.embeddings import LlamaCppEmbeddings
from langchain.llms import LlamaCpp


types = {
	"embedding": LlamaCppEmbeddings,
	"llm": LlamaCpp,
}

