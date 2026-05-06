#!/bin/bash
#
# SPDX-FileCopyrightText: 2024 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
set -e

source /etc/environment;
"$(dirname $(realpath $0))/pgsql/setup.sh";
source /etc/environment;

/opt/venv/bin/python -u ./main.py;

"$(dirname $(realpath $0))/pgsql/setup.sh" stop
