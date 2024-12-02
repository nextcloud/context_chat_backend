from langchain.schema import Document
from pydantic import BaseModel

from .injest import embed_sources

__all__ = [ 'embed_sources', 'InDocument' ]

class InDocument(BaseModel):
	documents: list[Document]  # the split documents of the same source
	userIds: list[str]
	source_id: str
	provider: str
	modified: int
