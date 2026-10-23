#!/bin/bash
#
# SPDX-FileCopyrightText: 2024 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
set -e

apt-get update
# gpg is installed explicitly so it survives the purge below, pgsql/install.sh needs it
apt-get install -y software-properties-common gpg
add-apt-repository -y ppa:deadsnakes/ppa
# software-properties-common is only needed for add-apt-repository and pulls in
# packagekit, polkit, systemd and python3-jwt, none of which the image uses
apt-get purge -y --autoremove software-properties-common
apt-get update
apt-get install -y --no-install-recommends python3.13 python3.13-venv
update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.13 1
