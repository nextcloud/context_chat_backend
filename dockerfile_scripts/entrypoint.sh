#!/bin/bash
#
# SPDX-FileCopyrightText: 2024 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
set -e

source /etc/environment;

# Ensure the container hostname resolves locally so sudo does not warn
# ("sudo: unable to resolve host <name>"). See #280.
if ! grep -q "[[:space:]]$(hostname)\b" /etc/hosts 2>/dev/null; then
	echo "127.0.1.1 $(hostname)" >> /etc/hosts || true
fi

"$(dirname $(realpath $0))/pgsql/setup.sh";
source /etc/environment;

/opt/venv/bin/python -u ./main.py;

"$(dirname $(realpath $0))/pgsql/setup.sh" stop
