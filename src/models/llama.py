from langchain.embeddings import LlamaCppEmbeddings
from langchain.llms import LlamaCpp
import ruamel.yaml as yaml

# this will raise an exception and is intended
with open('config.yaml') as f:
	config = yaml.safe_load(f)

_embedder = lambda: LlamaCppEmbeddings(**config.get('llama_embedder', {}))
_llm = lambda: LlamaCpp(**config.get('llama_llm', {}))

types = {
	"embedding": _embedder,
	"llm": _llm,
}
