#!/bin/bash
#
# SPDX-FileCopyrightText: 2025 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#

# Download and install the FRP client from the upstream release, verified against
# pinned checksums, as described in
# https://github.com/nextcloud/HaRP#adapting-exapps-to-use-harp
# When upgrading, update the version and copy both linux checksums from that
# release's frp_sha256_checksums.txt.
FRP_VERSION=0.71.1
FRP_AMD64_SHA256=1d9875210972a5d1a62b2dc4c48df45ab0af05d3ca1b5e494a014428259df803
FRP_ARM64_SHA256=8edf590b0c396fa42f9c147121a76af83cfc2002b08f5aef0ea1008c43482019

set -ex

ARCH=$(uname -m)
if [ "$ARCH" = "aarch64" ]; then
	FRP_ARCH="arm64"
	FRP_SHA256="${FRP_ARM64_SHA256}"
else
	FRP_ARCH="amd64"
	FRP_SHA256="${FRP_AMD64_SHA256}"
fi

FRP_URL="https://github.com/fatedier/frp/releases/download/v${FRP_VERSION}/frp_${FRP_VERSION}_linux_${FRP_ARCH}.tar.gz"
echo "Downloading FRP v${FRP_VERSION} for ${FRP_ARCH}..."
curl -fsSL "${FRP_URL}" -o /tmp/frp.tar.gz

ACTUAL_SHA256=$(sha256sum /tmp/frp.tar.gz | cut -d' ' -f1)
if [ "$ACTUAL_SHA256" != "$FRP_SHA256" ]; then
	echo "Checksum verification failed for FRP v${FRP_VERSION} (${FRP_ARCH})"
	echo "Expected: ${FRP_SHA256}"
	echo "Got:      ${ACTUAL_SHA256}"
	exit 1
fi

tar -C /tmp -xzf /tmp/frp.tar.gz
cp "/tmp/frp_${FRP_VERSION}_linux_${FRP_ARCH}/frpc" /usr/local/bin/frpc
chmod +x /usr/local/bin/frpc
rm -rf "/tmp/frp_${FRP_VERSION}_linux_${FRP_ARCH}" /tmp/frp.tar.gz
echo "FRP client installed successfully"
