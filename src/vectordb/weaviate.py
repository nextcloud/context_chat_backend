from typing import List, Optional
from dotenv import load_dotenv
from os import getenv
from langchain.schema.embeddings import Embeddings
from langchain.vectorstores import VectorStore, Weaviate
from weaviate import Client, AuthApiKey
from logging import error as log_error

from utils import value_of, CLASS_NAME
from vectordb.base import BaseVectorDB

load_dotenv()

# this is automatically picked up by the weaviate client
# WEAVIATE_API_KEY is also used if set
if value_of(getenv('WEAVIATE_URL')) is None:
	raise Exception('Error: environment variable WEAVIATE_URL is not set')


class_schema = {
	"properties": [
		{
			"dataType": ["text"],
			"description": "The actual text",
			"name": "text",
		},
		{
			"dataType": ["text"],
			"description": "The type of source/mimetype of file",
			"name": "type",
		},
		{
			"dataType": ["text"],
			"description": "The source of the text (for files: `file: fileId`)",
			"name": "source",
		},
		{
			"dataType": ["int"],
			"description": "Start index of chunk",
			"name": "start_index",
		},
		{
			# https://weaviate.io/developers/weaviate/config-refs/datatypes#datatype-date
			"dataType": ["int"],
			"description": "Last modified time of the file",
			"name": "modified",
		},
	],
	# TODO: optimisation for large number of objects
	"vectorIndexType": "hnsw",
	"vectorIndexConfig": {
		"skip": False,
		# "ef": 99,
		# "efConstruction": 127,  # minimise this for faster indexing
		# "maxConnections": 63,
	}
}


class VectorDB(BaseVectorDB):
	def __init__(self, embedder: Optional[Embeddings] = None):
		try:
			client = Client(
				url=getenv('WEAVIATE_URL'),
				timeout_config=(1, 20),
				**({
					'auth_client_secret': AuthApiKey(getenv('WEAVIATE_APIKEY')),
				} if value_of(getenv('WEAVIATE_APIKEY')) is not None else {}),
			)
		except Exception as e:
			raise Exception(f'Error: Weaviate connection error: {e}')

		if not client.is_ready():
			raise Exception('Error: Weaviate connection error')

		self.client = client
		self.embedder = embedder

	def setup_schema(self, user_id: str) -> None:
		if not self.client:
			raise Exception('Error: Weaviate client not initialised')

		if self.client.schema.exists(CLASS_NAME(user_id)):
			return

		self.client.schema.create_class({
			"class": CLASS_NAME(user_id),
			**class_schema,
		})

	def get_user_client(
			self,
			user_id: str,
			embedder: Optional[Embeddings] = None  # use this embedder if not None or use global embedder
		) -> Optional[VectorStore]:
		self.setup_schema(user_id)

		embeddings = None
		if self.embedder is not None:
			embeddings = self.embedder
		elif embedder is not None:
			embeddings = embedder

		return Weaviate(
			client=self.client,
			index_name=CLASS_NAME(user_id),
			text_key='text',
			embedding=embeddings,
			by_text=False,
		)

	def get_objects_from_sources(self, user_id: str, source_names: List[str]) -> dict:
		if not self.client:
			raise Exception('Error: Weaviate client not initialised')

		file_filter = {
			"path": ["source"],
			"operator": "ContainsAny",
			"valueTextList": source_names,
		}

		results = self.client.query \
			.get(CLASS_NAME(user_id), ['source', 'modified']) \
			.with_additional('id') \
			.with_where(file_filter) \
			.do()

		if results.get('errors') is not None:
			log_error(f'Error: Weaviate query error: {results.get("errors")}')
			return {}

		try:
			results = results['data']['Get'][CLASS_NAME(user_id)]
			output = {}
			for result in results:
				output[result['source']] = {
					'id': result['_additional']['id'],
					'modified': result['modified'],
				}
			return output
		except Exception as e:
			log_error(f'Error: Weaviate query error: {e}')
			return {}
