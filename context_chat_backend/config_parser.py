from pprint import pprint
from typing import TypedDict

from ruamel.yaml import YAML

from .models import models
from .vectordb import vector_dbs


class TConfig(TypedDict):
	vectordb: tuple[str, dict]
	embedding: tuple[str, dict]
	llm: tuple[str, dict]


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

	embedding = _first_in_list(config.get('embedding', {}), models['embedding'])
	if not embedding:
		raise AssertionError(
			f'Error: embedding model should be at least one of {models["embedding"]} in the config file'
		)

	llm = _first_in_list(config.get('llm', {}), models['llm'])
	if not llm:
		raise AssertionError(
			f'Error: llm model should be at least one of {models["llm"]} in the config file'
		)

	selected_config: TConfig = {
		'vectordb': vectordb,
		'embedding': embedding,
		'llm': llm,
	}

	pprint(f'Selected config: {selected_config}')

	return selected_config
