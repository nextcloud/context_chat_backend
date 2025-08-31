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
	for n in os.listdir(vector_db_path):
		if n == 'pgsql':
			continue
		if os.path.isdir(os.path.join(vector_db_path, n)):
			shutil.rmtree(os.path.join(vector_db_path, n))
		else:
			os.remove(os.path.join(vector_db_path, n))
