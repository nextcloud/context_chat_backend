from langchain.embeddings import HuggingFaceEmbeddings
# from langchain.llms import HuggingFacePipeline
import ruamel.yaml as yaml

# this will raise an exception and is intended
with open('config.yaml') as f:
	config = yaml.safe_load(f)

_embedder = lambda: HuggingFaceEmbeddings(**config.get('hugging_face_small_embedder', {}))

types = {
	"embedding": _embedder,
}
