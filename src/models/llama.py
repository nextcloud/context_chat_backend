from langchain.embeddings import LlamaCppEmbeddings
from langchain.llms import LlamaCpp
from ruamel.yaml import YAML

# this will raise an exception and is intended
with open('config.yaml') as f:
	yaml = YAML(typ='safe')
	config = yaml.load(f)

_embedder = lambda: LlamaCppEmbeddings(**config.get('llama_embedder', {}))
_llm = lambda: LlamaCpp(**config.get('llama_llm', {}))

types = {
	"embedding": _embedder,
	"llm": _llm,
}
