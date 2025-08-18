#!/bin/bash
#
# SPDX-FileCopyrightText: 2024 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
set -e

source /etc/environment;

if [ -z "${RAG_BACKEND}" ] || [ "${RAG_BACKEND,,}" = "builtin" ]; then
    "$(dirname $(realpath $0))/pgsql/setup.sh";
    source /etc/environment;
fi

python3 -u ./main.py;

if [ -z "${RAG_BACKEND}" ] || [ "${RAG_BACKEND,,}" = "builtin" ]; then
    "$(dirname $(realpath $0))/pgsql/setup.sh" stop
fi
