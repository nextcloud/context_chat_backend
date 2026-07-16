#
# SPDX-FileCopyrightText: 2026 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
import os

import sqlalchemy as sa

'''
Drop the "id" column from the access_list table since its auto-increment sequence
(32-bit integer) gets exhausted after many ownership modifications, causing:
  psycopg.errors.SequenceGeneratorLimitExceeded: nextval: reached maximum value of
  sequence "access_list_id_seq" (2147483647)
Also, "id" isn't used anywhere except as a primary key.

The composite (uid, source_id) key is promoted to primary key instead.
'''


def run(_previous_version: int):
	db_url = os.environ.get('CCB_DB_URL')
	if not db_url:
		print('CCB_DB_URL not set, skipping "id" column drop from "access_list" table', flush=True)
		return

	engine = sa.create_engine(db_url)
	with engine.connect() as conn:
		# Drop the unique index that we'll convert to primary key
		conn.execute(sa.text(
			'DROP INDEX IF EXISTS uid_chunk_id_idx'
		))
		# Drop the id column (also removes the old PK constraint and sequence)
		conn.execute(sa.text(
			'ALTER TABLE access_list DROP COLUMN IF EXISTS id'
		))
		# Add the primary key constraint using the existing unique columns
		conn.execute(sa.text(
			'ALTER TABLE access_list ADD CONSTRAINT access_list_pkey PRIMARY KEY (uid, source_id)'
		))
		conn.commit()
