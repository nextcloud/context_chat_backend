#
# SPDX-FileCopyrightText: 2024 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
from enum import Enum


class DbException(Exception):
	...


class SafeDbException(Exception):
	...


class UpdateAccessOp(Enum):
	allow = 'allow'
	deny = 'deny'
