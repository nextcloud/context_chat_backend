from dotenv import load_dotenv
import os
from langchain.text_splitter import TextSplitter, RecursiveCharacterTextSplitter # noqa
from langchain.vectorstores import Weaviate
from langchain.docstore.document import Document
from langchain.embeddings import LlamaCppEmbeddings
from weaviate import Client, AuthApiKey
from threading import Timer
from typing import Callable, Dict, List, Iterator
from typing_extensions import Any
from werkzeug.datastructures.file_storage import FileStorage

from utils import CLASS_NAME, value_of

from langchain.embeddings import HuggingFaceEmbeddings

HuggingFaceEmbeddings()

# TODO: place only the init code here
# other methods should be imported from other files

load_dotenv()

_WEAVIATE_URL = os.getenv('WEAVIATE_URL')

_EMBEDDER_MODEL_PATH = "./models/codellama-7b.Q5_K_M.gguf"
_EMBEDDER_CONTEXT_LENGTH = 2048

# user weaviate clients (access to user specific classes)
_user_clients: Dict[str, Weaviate] = {}

# TODO: multiple options for the embedding model
embedder = LlamaCppEmbeddings(
	model_path=_EMBEDDER_MODEL_PATH,
	n_ctx=_EMBEDDER_CONTEXT_LENGTH
)


def _clear_user_clients():
	global _user_clients
	_user_clients = {}


# clear user clients once a day
timer = Timer(84000, _clear_user_clients)
timer.start()


if _WEAVIATE_URL is None or _WEAVIATE_URL.strip() == '':
	raise Exception('no WEAVIATE_URL present in the environment')

weaviate_client = None
# instantiate weaviate client with or without apikey
if value_of(os.getenv('WEAVIATE_APIKEY')) is None:
	weaviate_client = Client(
		url=_WEAVIATE_URL,
		timeout_config=(10, 20),
	)
else:
	weaviate_client = Client(
		url=_WEAVIATE_URL,
		auth_client_secret=AuthApiKey(os.getenv('WEAVIATE_APIKEY')),
		timeout_config=(10, 20),
	)


def _get_client(user_id: str):
	# setup initial schema if not already there (should ideally be executed on
	# app install on NC)
	setup_schema(user_id)

	if _user_clients.get(user_id) is not None:
		return _user_clients[user_id]

	client = _user_clients[user_id] = Weaviate(
		client=weaviate_client,
		index_name=CLASS_NAME(user_id),
		text_key="text",  # where raw text would be present in the db
		embedding=embedder,
	)

	client.embeddings = embedder
	return client

# "users" | "files" | "vectors"


def setup_schema(user_id: str):
	if weaviate_client.schema.exists(CLASS_NAME(user_id)):
		return

	class_obj = {
		"class": CLASS_NAME(user_id),
		"properties": [
			{
				"dataType": ["text"],
				"description": "The actual text",
				"name": "text",
			},
			# {
			# 	"dataType": ["text"],
			# 	"description": "The type of source",
			# 	"name": "type",
			# },
			{
				"dataType": ["text"],
				"description": "The source file",
				"name": "source",
			},
			{
				"dataType": ["int"],
				"description": "Start index of chunk",
				"name": "start_index",
			},
			{
				# https://weaviate.io/developers/weaviate/config-refs/datatypes#datatype-date
				"dataType": ["date"],
				"description": "Last modified time of the file",
				"name": "modified",
			},
		],
	}

	weaviate_client.schema.create_class(class_obj)


class JSONTextSplitter(RecursiveCharacterTextSplitter):
	def __init__(self, **kwargs: Any) -> None:
		"""Initialize a JSONTextSplitter."""
		# TODO: process JSON in a better way
		separators = [ "{", "}", "[", "]", "," ]
		super().__init__(separators=separators, **kwargs)


# TODO: make custom splitters based on file extensions,
# check done early on
class PlopSplitter(TextSplitter):
	def __init__(
			self,
			chunk_size: int = 4000,
			chunk_overlap: int = 200,
			length_function: Callable[[str], int] = ...,
			keep_separator: bool = False,
			add_start_index: bool = True,
			strip_whitespace: bool = True,
		) -> None:
		super().__init__(chunk_size, chunk_overlap, length_function,
			keep_separator, add_start_index, strip_whitespace)  # noqa: E128

	def split_text(self, text: str, source: str | None = None) -> List[str]:
		if source.endswith('.log') or source.endswith('.json'):
			text = text.replace("\n", "")

			# FIXME: anti-pattern, do this file extension check earlier
			jsonsplitter = JSONTextSplitter(
				chunk_size=self._chunk_size,
				chunk_overlap=0,
				add_start_index=True,
				strip_whitespace=True,
				length_function=len,
			)

			output = jsonsplitter.split_text(text)
			print(f'jsonsplitter: {output}')
			return output

		return filter(lambda x: x != "", map(lambda x: x.strip(), text.split(".")))


def delete_files(user_id: str, filenames: List[str]):
	file_filter = {
		"path": ["source"],
		"operator": "ContainsAny",
		"valueTextList": filenames
	}

	result = weaviate_client.batch.delete_objects(
		CLASS_NAME(user_id), file_filter
	)

	"""
	of the form:
	{
		"failed": 0,
		"limit": 10000,
		"matches": 14,
		"objects": null,
		"successful": 14
	}
	"""
	if result.get('results') is not None:
		return result['results']

	return { "failed": 1 }


# TODO: make it async (return an inference key that can be queried later on)
def embed_files(user_id: str, filesIter: Iterator[FileStorage]) -> List[str]:
	client = _get_client(user_id)

	print('embedding files...')

	raw_documents = [
		Document(
			page_content=file.stream.read().decode(),
			metadata={
				# TODO: filepath
				'source': file.filename,
				'modified': file.headers.get('modification_time', type=int, default=0)
			}
		) for file in filesIter
	]

	text_splitter = PlopSplitter(
		chunk_size=2000,
		chunk_overlap=100,
		keep_separator=True,
		add_start_index=True,
		strip_whitespace=True,
		length_function=len,
	)
	documents = text_splitter.split_documents(raw_documents)

	return client.add_documents(documents)


def get_similar_documents(user_id: str, query: str, limit: int = 5) -> dict:
	embedding = embedder.embed_query(query)
	content: Dict[str, Any] = {"vector": embedding}
	return weaviate_client.query \
		.get(CLASS_NAME(user_id), ['text', 'source', 'start_index', 'modified']) \
		.with_near_vector(content) \
		.with_limit(limit) \
		.do()


def list_vectors(user_id: str) -> Dict:
	setup_schema(user_id)
	# Optionally retrieve the vector embedding by adding `vector` to the
	# _additional fields
	return weaviate_client.query \
		.get(CLASS_NAME(user_id), ['text', 'source', 'start_index', 'modified']) \
		.with_limit(100) \
		.do()

