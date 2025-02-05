#!/bin/bash
#
# SPDX-FileCopyrightText: 2024 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#

set -e

# Environment variables
source "$(dirname $(realpath $0))/env"

if [ x"$1" == "xstop" ]; then
    echo -n Stopping PostgreSQL...
    sudo -u postgres ${PG_BIN}/pg_ctl -D "$DATA_DIR" -l "${DATA_DIR}/logfile" -o "-p ${PG_PORT}" stop
    exit 0
fi

# Check if EXTERNAL_DB is set
if [ -n "${EXTERNAL_DB}" ]; then
    if [[ "$EXTERNAL_DB" != "postgresql+psycopg://"* ]]; then
        echo "EXTERNAL_DB must be a PostgreSQL URL and start with 'postgresql+psycopg://'"
        exit 1
    fi

    echo "Using EXTERNAL_DB, CCB_DB_URL is set to: $EXTERNAL_DB"

    if ! grep -q "^export EXTERNAL_DB=" /etc/environment; then
        echo "export EXTERNAL_DB=\"$EXTERNAL_DB\"" >> /etc/environment
        echo "export CCB_DB_URL=\"$EXTERNAL_DB\"" >> /etc/environment
    fi
    exit 0
fi

# Ensure the directory exists and has the correct permissions
mkdir -p "$DATA_DIR"
chmod +rx "${APP_PERSISTENT_STORAGE:-persistent_storage}"
chmod +rx "$BASE_DIR"
chown -R postgres:postgres "$DATA_DIR"

if [ ! -d "$DATA_DIR/base" ]; then
    echo "Initializing the PostgreSQL database..."
    sudo -u postgres ${PG_BIN}/initdb -D "$DATA_DIR" -E UTF8
fi

echo "Starting PostgreSQL..."
sudo -u postgres ${PG_BIN}/pg_ctl -D "$DATA_DIR" -l "${DATA_DIR}/logfile" -o "-p ${PG_PORT}" start

echo "Waiting for PostgreSQL to start..."
until sudo -u postgres ${PG_SQL} -c "SELECT 1" > /dev/null 2>&1; do
    sleep 1
    echo -n "."
done
echo "PostgreSQL is up and running."

if [ -n "${CCB_DB_URL}" ]; then
    echo "CCB_DB_URL is already set. Skipping database setup."
    exit 0
fi

# Check if the user exists and create if not
sudo -u postgres $PG_SQL -c "SELECT 1 FROM pg_user WHERE usename = '$CCB_DB_USER'" | grep -q 1 || \
sudo -u postgres $PG_SQL -c "CREATE USER $CCB_DB_USER WITH PASSWORD '$CCB_DB_PASS';" && \
sudo -u postgres $PG_SQL -c "ALTER USER $CCB_DB_USER WITH SUPERUSER;"

# Check if the database exists and create if not
sudo -u postgres $PG_SQL -c "SELECT 1 FROM pg_database WHERE datname = '$CCB_DB_NAME'" | grep -q 1 || \
sudo -u postgres $PG_SQL -c "CREATE DATABASE $CCB_DB_NAME OWNER $CCB_DB_USER;"

# Check or create the vector extension
sudo -u postgres $PG_SQL -c "CREATE EXTENSION IF NOT EXISTS vector"

if ! grep -q "^export CCB_DB_URL=" /etc/environment; then
    echo "export CCB_DB_URL=\"postgresql+psycopg://$CCB_DB_USER:$CCB_DB_PASS@localhost:${PG_PORT}/$CCB_DB_NAME\"" >> /etc/environment
fi
