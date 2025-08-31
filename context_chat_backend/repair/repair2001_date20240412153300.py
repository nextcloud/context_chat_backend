#
# SPDX-FileCopyrightText: 2024 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
import os

'''
This script is used to repair the persistent storage by deleting the config file.
It is done to ensure that the correct config file is moved to the persistent storage
in the hw_detect.sh script for existing deployments.
'''

persistent_storage_path = os.getenv('APP_PERSISTENT_STORAGE', 'persistent_storage')
persistent_config_path = os.path.join(persistent_storage_path, 'config.yaml')

if os.path.exists(persistent_config_path):
	os.unlink(persistent_config_path)
