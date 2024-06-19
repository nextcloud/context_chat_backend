#!/usr/bin/env python3

import os
import re
from importlib import import_module


def get_previous_version(version_info_path: str) -> tuple[int, bool]:
	'''
	'+' at the end of the patch version indicates that repairs have been run.
	'''
	if not os.path.exists(version_info_path):
		version_string = os.environ['APP_VERSION']
	else:
		with open(version_info_path) as f:
			version_string = f.read()

	major, minor, patch = version_string.split('.')
	current_repairs_run = patch.endswith('+') and version_string.rstrip('+') == os.environ['APP_VERSION']

	return (int(major + minor.zfill(3)), current_repairs_run)


def main():
	'''
	Run repairs that have not been run before.
	Repair files can either have no functions or a run() function.
	'''
	persistent_storage_path = os.getenv('APP_PERSISTENT_STORAGE', 'persistent_storage')
	version_info_path = os.path.join(persistent_storage_path, 'version.info')

	all_filenames = os.listdir('context_chat_backend/repair')
	repair_filenames = [f for f in all_filenames if f.startswith('repair') and f.endswith('.py')]
	repair_filenames.sort(reverse=True)

	(previous_app_version, current_repairs_run) = get_previous_version(version_info_path)

	if current_repairs_run:
		return

	for repair_filename in repair_filenames:
		pattern = re.compile(r'^repair(\d+)_date\d+\.py$')
		matches = pattern.match(repair_filename)
		if not matches:
			return

		introduced_version = int(matches.group(1))

		if introduced_version < previous_app_version:
			break

		mod = import_module(f'.repair.{repair_filename[:-3]}', 'context_chat_backend')
		if hasattr(mod, 'run'):
			mod.run()

	with open(version_info_path, 'w') as f:
		f.write(os.environ['APP_VERSION'] + '+')


if __name__ == '__main__':
	main()
