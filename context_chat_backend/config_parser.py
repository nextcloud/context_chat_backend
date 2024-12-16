#
# SPDX-FileCopyrightText: 2024 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
from ruamel.yaml import YAML

from .models.loader import models
from .types import TConfig
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

	return TConfig(
		debug=config.get('debug', False),
		disable_aaa=config.get('disable_aaa', False),
		httpx_verify_ssl=config.get('httpx_verify_ssl', True),
		use_colors=config.get('use_colors', True),
		uvicorn_workers=config.get('uvicorn_workers', 1),
		embedding_chunk_size=config.get('embedding_chunk_size', 1000),
		doc_parser_worker_limit=config.get('doc_parser_worker_limit', 10),

		vectordb=vectordb,
		embedding=config.get('embedding', {}), # for a more appropriate response
		llm=llm,
	)
