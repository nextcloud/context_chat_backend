#
# SPDX-FileCopyrightText: 2024 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
import os
import shutil

'''
Reset the vector db in favour of a new embedding model
'''

vector_db_path = os.path.join(
	os.getenv('APP_PERSISTENT_STORAGE', 'persistent_storage'),
	'vector_db_data',
)

if os.path.exists(vector_db_path):
	shutil.rmtree(vector_db_path)
	os.makedirs(vector_db_path, mode=0o770)
