#!/bin/bash

apt-get update
apt-get install -y software-properties-common
add-apt-repository -y ppa:deadsnakes/ppa
apt-get update
apt-get install -y --no-install-recommends python3.11 python3.11-venv python3-pip vim git pciutils
update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1
