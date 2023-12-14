#!/usr/bin/env python3

from pprint import pprint

from ruamel.yaml import YAML
from schackles import create_server, models, vector_dbs


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


if __name__ == '__main__':
	with open('config.yaml') as f:
		try:
			yaml = YAML(typ='safe')
			config: dict = yaml.load(f)
		except Exception as e:
			raise AssertionError('Error: could not load config.yaml') from e

	selected_config = {
		'vectordb': _first_in_list(config.get('vectordb', {}), vector_dbs),
		'embedding': _first_in_list(config.get('embedding', {}), models['embedding']),
		'llm': _first_in_list(config.get('llm', {}), models['llm']),
	}

	if not selected_config['vectordb']:
		raise AssertionError(
			f'Error: vectordb should be at least one of {vector_dbs} in the config file'
		)

	if not selected_config['embedding']:
		raise AssertionError(
			f'Error: embedding model should be at least one of {models["embedding"]} in the config file'
		)

	if not selected_config['llm']:
		raise AssertionError(
			f'Error: llm model should be at least one of {models["llm"]} in the config file'
		)

	pprint(f'Selected config: {selected_config}')

	create_server(selected_config)
