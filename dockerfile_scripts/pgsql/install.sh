#!/bin/bash

# Stolen from https://github.com/cloud-py-api/flow

set -e

# Environment variables
source "$(dirname $(realpath $0))/env"

apt-get update
apt-get install -y curl sudo

# Check if PostgreSQL is installed by checking for the existence of binary files
if [ -d "$PG_BIN" ]; then
    echo "PostgreSQL binaries found."
else
    echo "PostgreSQL binaries not found."
    echo "Adding the PostgreSQL APT repository..."
    VERSION="$(awk -F'=' '/^VERSION_CODENAME=/{ print $NF }' /etc/os-release)"
    echo "deb http://apt.postgresql.org/pub/repos/apt ${VERSION}-pgdg main" >/etc/apt/sources.list.d/pgdg.list
    curl -sSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor --output /etc/apt/trusted.gpg.d/postgresql.gpg
    echo "Installing PostgreSQL..."
    apt-get update && apt-get install -y postgresql-$PG_VERSION postgresql-$PG_VERSION-pgvector
fi
