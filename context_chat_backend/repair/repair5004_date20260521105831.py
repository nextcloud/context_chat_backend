#
# SPDX-FileCopyrightText: 2026 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
import os

import sqlalchemy as sa

'''
Add an index on access_list.source_id to speed up ON DELETE CASCADE
triggered when deleting from the docs table.
Without this index, the CASCADE performs a sequential scan of access_list
for each deleted doc row, causing very slow batch deletes.
'''


def run(_previous_version: int):
	db_url = os.environ.get('CCB_DB_URL')
	if not db_url:
		print('CCB_DB_URL not set, skipping access_list index migration', flush=True)
		return

	engine = sa.create_engine(db_url)
	with engine.connect() as conn:
		conn.execute(sa.text(
			'CREATE INDEX IF NOT EXISTS idx_access_list_source_id ON access_list (source_id)'
		))
		conn.commit()
