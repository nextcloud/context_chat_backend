#!/usr/bin/env python3

import os
import re
from importlib import import_module


def get_previous_version(version_info_path: str) -> tuple[int, bool]:
	'''
	'+' at the end of the patch version indicates that repairs have been run.
	'''
	if not os.path.exists(version_info_path):
		return (0, False)

	with open(version_info_path) as f:
		version_string = f.read()

	major, minor, patch = version_string.split('.')
	repairs_pending = not (patch.endswith('+') and version_string.rstrip('+') == os.environ['APP_VERSION'])

	return (int(major + minor.zfill(3)), repairs_pending)


def main():
	'''
	Run repairs that have not been run before.
	Repair files can either have no functions or a run() function.
	'''
	print('Running repairs...', flush=True)

	persistent_storage_path = os.getenv('APP_PERSISTENT_STORAGE', 'persistent_storage')
	version_info_path = os.path.join(persistent_storage_path, 'version.info')

	all_filenames = os.listdir('context_chat_backend/repair')
	repair_filenames = [f for f in all_filenames if f.startswith('repair') and f.endswith('.py')]
	repair_filenames.sort(reverse=True)

	(previous_app_version, repairs_pending) = get_previous_version(version_info_path)

	if not repairs_pending:
		print('No repairs are required.', flush=True)
		return

	for repair_filename in repair_filenames:
		pattern = re.compile(r'^repair(\d+)_date\d+\.py$')
		matches = pattern.match(repair_filename)
		if not matches:
			print(f'Ignoring invalid repair file: {repair_filename}', flush=True)
			continue

		introduced_version = int(matches.group(1))

		if introduced_version < previous_app_version:
			print(f'No repairs to run for version {introduced_version}.', flush=True)
			break

		print(f'Running repair {repair_filename}...', flush=True, end='')

		mod = import_module(f'.repair.{repair_filename[:-3]}', 'context_chat_backend')
		if hasattr(mod, 'run'):
			mod.run(previous_app_version)

		print('completed.', flush=True)

	with open(version_info_path, 'w') as f:
		f.write(os.environ['APP_VERSION'] + '+')

	print('Repairs completed.', flush=True)


if __name__ == '__main__':
	main()
