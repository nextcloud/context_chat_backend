from langchain.embeddings import HuggingFaceEmbeddings
# from langchain.llms import HuggingFacePipeline
from ruamel.yaml import YAML

# this will raise an exception and is intended
with open('config.yaml') as f:
	yaml = YAML(typ='safe')
	config = yaml.load(f)

_embedder = lambda: HuggingFaceEmbeddings(**config.get('hugging_face_small_embedder', {}))

types = {
	"embedding": _embedder,
}
