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
FRP_VERSION=0.71.0
FRP_AMD64_SHA256=84f27e39f11169f7adcef8e8b70c9329de17747b1f14dad9fb95eef5682ea716
FRP_ARM64_SHA256=f33c293c275d8fc68c654b6fba8f10b2551d6463d09a9fc9cffb7227eae82266

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
