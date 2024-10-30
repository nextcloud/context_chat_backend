#!/bin/bash

set -e

source /etc/environment
"$(dirname $(realpath $0))/pgsql/setup.sh"
source /etc/environment

python3 -u "$(dirname $(dirname $(realpath $0)))/main.py"
