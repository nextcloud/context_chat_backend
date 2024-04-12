#!/usr/bin/env python3

import os
from importlib import import_module


def main():
	persistent_storage_path = os.getenv('APP_PERSISTENT_STORAGE', 'persistent_storage')
	repair_info_path = os.path.join(persistent_storage_path, 'repair.info')

	if not os.path.exists(repair_info_path):
		# touch
		open(repair_info_path, 'w').close()

	all_filenames = os.listdir('context_chat_backend/repair')
	repair_filenames = [f for f in all_filenames if f.startswith('repair') and f.endswith('.py')]

	with open(repair_info_path) as f:
		repair_info = f.read().split('\n')
		if repair_info[-1] == '':
			repair_info.pop()

	for repair_filename in repair_filenames:
		if repair_filename in repair_info:
			continue

		import_module(f'.repair.{repair_filename[:-3]}', 'context_chat_backend')
		repair_info.append(repair_filename)

	with open(repair_info_path, 'w') as f:
		f.write('\n'.join(repair_info))

if __name__ == '__main__':
	main()
