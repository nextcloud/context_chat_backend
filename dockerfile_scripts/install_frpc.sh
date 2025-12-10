#!/bin/bash
#
# SPDX-FileCopyrightText: 2025 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#

# Download and install FRP client
set -ex; \
	ARCH=$(uname -m); \
	if [ "$ARCH" = "aarch64" ]; then \
		FRP_URL="https://raw.githubusercontent.com/nextcloud/HaRP/dadcb7cfeb7a6d058ca2acb5622807269239f369/exapps_dev/frp_0.61.1_linux_arm64.tar.gz"; \
	else \
		FRP_URL="https://raw.githubusercontent.com/nextcloud/HaRP/dadcb7cfeb7a6d058ca2acb5622807269239f369/exapps_dev/frp_0.61.1_linux_amd64.tar.gz"; \
	fi; \
	echo "Downloading FRP client from $FRP_URL"; \
	curl -L "$FRP_URL" -o /tmp/frp.tar.gz; \
	tar -C /tmp -xzf /tmp/frp.tar.gz; \
	mv /tmp/frp_0.61.1_linux_* /tmp/frp; \
	cp /tmp/frp/frpc /usr/local/bin/frpc; \
	chmod +x /usr/local/bin/frpc; \
	rm -rf /tmp/frp /tmp/frp.tar.gz
