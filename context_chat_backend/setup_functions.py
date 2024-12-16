#
# SPDX-FileCopyrightText: 2024 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
import os
import subprocess

from dotenv import load_dotenv

from .repair import runner

__all__ = ['setup_env_vars', 'repair_run', 'ensure_config_file']


def ensure_config_file():
	'''
	Ensures the config file is present.
	'''
	subprocess.run(['./hwdetect.sh', 'config'], check=True, shell=False)  # noqa: S603


def repair_run():
	'''
	Runs the repair script.
	'''
	runner.main()


def setup_env_vars():
	'''
	Sets up the environment variables for persistent storage.
	'''
	load_dotenv()

	persistent_storage = os.getenv('APP_PERSISTENT_STORAGE', 'persistent_storage')

	vector_db_dir = os.path.join(persistent_storage, 'vector_db_data')
	if not os.path.exists(vector_db_dir):
		os.makedirs(vector_db_dir, 0o750, True)

	model_dir = os.path.join(persistent_storage, 'model_files')
	if not os.path.exists(model_dir):
		os.makedirs(model_dir, 0o750, True)

	config_path = os.path.join(persistent_storage, 'config.yaml')

	os.environ['APP_PERSISTENT_STORAGE'] = persistent_storage
	os.environ['VECTORDB_DIR'] = vector_db_dir
	os.environ['MODEL_DIR'] = model_dir
	os.environ['SENTENCE_TRANSFORMERS_HOME'] = os.getenv('SENTENCE_TRANSFORMERS_HOME', model_dir)
	os.environ['HF_HOME'] = os.getenv('HF_HOME', model_dir)
	os.environ['CC_CONFIG_PATH'] = os.getenv('CC_CONFIG_PATH', config_path)
