from os import getenv, path

from langchain_community.embeddings.llamacpp import LlamaCppEmbeddings
from langchain_community.llms.llamacpp import LlamaCpp
from langchain_core.embeddings import Embeddings


class LazyLlama(Embeddings):
    def __init__(self, /, **kwargs):
        self.kwargs = kwargs
        self.lcpp = None

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if self.lcpp is None:
            self.lcpp = LlamaCppEmbeddings(**self.kwargs)
        return self.lcpp.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        if self.lcpp is None:
            self.lcpp = LlamaCppEmbeddings(**self.kwargs)
        return self.lcpp.embed_query(text)


def get_model_for(model_type: str, model_config: dict):
    model_dir = getenv("MODEL_DIR", "persistent_storage/model_files")
    if str(model_config.get("model_path")).startswith("/"):
        model_dir = ""

    model_path = path.join(model_dir, model_config.get("model_path", ""))

    if model_config is None:
        return None

    if model_type == "embedding":
        return LazyLlama(**{**model_config, "model_path": model_path})

    if model_type == "llm":
        return LlamaCpp(**{**model_config, "model_path": model_path})

    return None
