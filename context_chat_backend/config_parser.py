#
# SPDX-FileCopyrightText: 2024 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
import os

from ruamel.yaml import YAML

from .models.loader import models
from .types import TConfig, TEmbeddingAuthApiKey, TEmbeddingAuthBasic, TEmbeddingConfig
from .utils import value_of
from .vectordb.loader import vector_dbs


def _first_in_list(
	input_dict: dict[str, dict],
	supported_list: list[str]
) -> tuple[str, dict] | None:
	'''
	Find the first matching item in the input list from the supported list.
	This is done to find the first supported item in the config file.
	'''
	for input_item, value in input_dict.items():
		if input_item in supported_list:
			return (input_item, value or {})

	return None


def get_config(file_path: str) -> TConfig:
	'''
	Get the config from the given file path (relative to the root directory).
	'''
	with open(file_path) as f:
		try:
			yaml = YAML(typ='safe')
			config: dict = yaml.load(f)
		except Exception as e:
			raise AssertionError('Error: could not load config from', file_path, 'file') from e

	vectordb = _first_in_list(config.get('vectordb', {}), vector_dbs)
	if not vectordb:
		raise AssertionError(
			f'Error: vectordb should be at least one of {vector_dbs} in the config file'
		)

	llm = _first_in_list(config.get('llm', {}), models['llm'])
	if not llm:
		raise AssertionError(
			f'Error: llm model should be at least one of {models["llm"]} in the config file'
		)

	# convert protocol, host and port to base_url
	embedding = config.get('embedding')
	if (embedding is None or not isinstance(embedding, dict)) and not os.getenv('CC_EM_BASE_URL'):
		raise AssertionError(
			'Error: "embedding" key should be defined in the config file or CC_EM_BASE_URL env var should be set in the'
			' Deploy Options.'
		)

	if os.getenv('CC_EM_BASE_URL'):
		if os.getenv('CC_EM_APIKEY'):
			auth = TEmbeddingAuthApiKey(apikey=os.environ['CC_EM_APIKEY'])
		elif os.getenv('CC_EM_USERNAME') and os.getenv('CC_EM_PASSWORD'):
			auth = TEmbeddingAuthBasic(
				username=os.environ['CC_EM_USERNAME'],
				password=os.environ['CC_EM_PASSWORD'],
			)
		else:
			auth = None

		try:
			# override embedding config from env vars
			embedding_config = TEmbeddingConfig(
				base_url=os.environ['CC_EM_BASE_URL'],
				model_name=value_of(os.getenv('CC_EM_MODEL_NAME', None)),
				auth=auth,
				remote_service=True,
				workers=0,
				request_timeout=embedding.get('request_timeout', 1800) if embedding else 1800,
			)
		except Exception as e:
			raise AssertionError(
				'Error: could not create embedding config from env vars'
			) from e

	elif embedding is None:
		raise AssertionError(
			'Error: "embedding" key should be defined in the config file if CC_EM_BASE_URL env var is not set in the'
			' Deploy Options.'
		)
	else:
		# embedding from config file
		if 'protocol' in embedding and 'host' in embedding and 'port' in embedding:
			embedding['base_url'] = f"{embedding['protocol']}://{embedding['host']}:{embedding['port']}/v1"
			del embedding['protocol']
			del embedding['host']
			del embedding['port']

		try:
			embedding_config = TEmbeddingConfig(**embedding)
		except Exception as e:
			raise AssertionError('Error: could not create embedding config from config file') from e

	return TConfig(
		debug=config.get('debug', False),
		uvicorn_log_level=config.get('uvicorn_log_level', 'info'),
		disable_aaa=config.get('disable_aaa', False),
		httpx_verify_ssl=config.get('httpx_verify_ssl', True),
		use_colors=config.get('use_colors', True),
		uvicorn_workers=config.get('uvicorn_workers', 1),
		embedding_chunk_size=config.get('embedding_chunk_size', 1000),
		doc_parser_worker_limit=config.get('doc_parser_worker_limit', 10),

		vectordb=vectordb,
		embedding=embedding_config,
		llm=llm,
	)
