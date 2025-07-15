# SPDX-FileCopyrightText: 2023 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
FROM nvidia/cuda:12.2.2-runtime-ubuntu22.04

ARG CCB_DB_NAME=ccb
ARG CCB_DB_USER=ccbuser
ARG CCB_DB_PASS=ccbpass

ENV CCB_DB_NAME ${CCB_DB_NAME}
ENV CCB_DB_USER ${CCB_DB_USER}
ENV CCB_DB_PASS ${CCB_DB_PASS}
ENV DEBIAN_FRONTEND noninteractive
ENV NVIDIA_VISIBLE_DEVICES all
ENV NVIDIA_DRIVER_CAPABILITIES compute
ENV AA_DOCKER_ENV 1

# Set working directory
WORKDIR /app

# Install dependencies
ADD dockerfile_scripts/install_deps.sh dockerfile_scripts/install_deps.sh
RUN ./dockerfile_scripts/install_deps.sh
ADD dockerfile_scripts/install_py11.sh dockerfile_scripts/install_py11.sh
RUN ./dockerfile_scripts/install_py11.sh
ADD dockerfile_scripts/pgsql dockerfile_scripts/pgsql
RUN ./dockerfile_scripts/pgsql/install.sh
RUN apt-get autoclean
ADD dockerfile_scripts/entrypoint.sh dockerfile_scripts/entrypoint.sh

# Restore interactivity
ENV DEBIAN_FRONTEND dialog

# Copy requirements files
COPY requirements.txt .

# Install requirements
RUN python3 -m pip install --no-cache-dir --upgrade pip setuptools wheel
RUN python3 -m pip install --no-cache-dir https://github.com/abetlen/llama-cpp-python/releases/download/v0.3.4-cu122/llama_cpp_python-0.3.4-cp311-cp311-linux_x86_64.whl
RUN sed -i '/llama_cpp_python/d' requirements.txt
RUN python3 -m pip install --no-cache-dir -r requirements.txt && python3 -m pip cache purge

# Copy application files
COPY context_chat_backend context_chat_backend
COPY main.py .
COPY main_em.py .
COPY config.?pu.yaml .
COPY logger_config.yaml .
COPY logger_config_em.yaml .
COPY hwdetect.sh .
COPY supervisord.conf /etc/supervisor/supervisord.conf

ENTRYPOINT ["supervisord", "-c", "/etc/supervisor/supervisord.conf"]
