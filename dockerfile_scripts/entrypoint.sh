#!/bin/bash

set -e

source /etc/environment;
"$(dirname $(realpath $0))/pgsql/setup.sh";
source /etc/environment;

python3 -u ./main.py;

"$(dirname $(realpath $0))/pgsql/setup.sh" stop
