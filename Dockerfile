# SPDX-FileCopyrightText: 2023 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
ARG CPU_IMAGE=ubuntu:22.04
ARG CUDA_DEVEL_IMAGE=nvidia/cuda:12.4.1-devel-ubuntu22.04
ARG CUDA_RUNTIME_IMAGE=nvidia/cuda:12.4.1-runtime-ubuntu22.04
ARG LLAMA_CPP_PYTHON_VERSION=0.3.20

# ============================================================
# CPU / ARM builder
# Builds llama_cpp_python for any x86_64 (AVX+, Sandy Bridge 2011+)
# and for arm64 (NEON always available).
# ubuntu:22.04 is a multi-arch image so this stage covers both.
#
# GGML_NATIVE=OFF: no -march=native; the host build machine's SIMD
# capabilities are not baked in.  AVX/AVX2/FMA/F16C default to ON in
# llama.cpp cmake and are used when the CPU supports them at runtime
# (the ggml_cpu_has_*() guards).  On arm64 those x86 flags are never
# emitted by cmake, so NEON/SVE detection remains intact.
# ============================================================
FROM ubuntu:22.04 AS llama-builder-cpu
ARG LLAMA_CPP_PYTHON_VERSION

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /build
ADD dockerfile_scripts/install_py11.sh dockerfile_scripts/install_py11.sh
RUN ./dockerfile_scripts/install_py11.sh
# install_py11.sh leaves apt lists in place – install build tools in one layer
RUN apt-get install -y --no-install-recommends \
        python3.11-dev \
        cmake build-essential ninja-build git \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN python3.11 -m pip install --no-cache-dir --upgrade pip setuptools wheel

ENV CMAKE_ARGS="-DGGML_NATIVE=OFF"

RUN python3.11 -m pip wheel \
    --no-cache-dir \
    --no-binary llama-cpp-python \
    --wheel-dir=/wheels \
    "llama-cpp-python==${LLAMA_CPP_PYTHON_VERSION}"

# ============================================================
# CUDA (NVIDIA) builder
# Builds llama_cpp_python with CUDA support.
# sm_90 is the maximum compute capability supported by CUDA 12.4
# (Hopper / H100).  Blackwell sm_100 requires CUDA 12.8+.
# ============================================================
FROM ${CUDA_DEVEL_IMAGE} AS llama-builder-cuda
ARG LLAMA_CPP_PYTHON_VERSION

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /build
ADD dockerfile_scripts/install_py11.sh dockerfile_scripts/install_py11.sh
RUN ./dockerfile_scripts/install_py11.sh
# gcc-12 is required: Ubuntu 22.04 ships gcc-11 by default which CUDA 12.4
# treats as "unsupported"; we pin gcc-12 to match the official CI workflow.
RUN apt-get install -y --no-install-recommends \
        python3.11-dev \
        cmake build-essential ninja-build git \
        gcc-12 g++-12 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

ENV CC=/usr/bin/gcc-12
ENV CXX=/usr/bin/g++-12
ENV CUDAHOSTCXX=/usr/bin/g++-12

RUN python3.11 -m pip install --no-cache-dir --upgrade pip setuptools wheel

# Architecture list aligned with the official llama-cpp-python CUDA CI workflow:
#   https://github.com/abetlen/llama-cpp-python/blob/main/.github/workflows/build-wheels-cuda.yaml
ENV CMAKE_ARGS="-DGGML_CUDA=ON -DGGML_CUDA_FORCE_MMQ=ON -DGGML_NATIVE=OFF \
    -DCMAKE_CUDA_ARCHITECTURES=70-real;75-real;80-real;86-real;89-real;90-real;90-virtual \
    -DCMAKE_CUDA_FLAGS=--allow-unsupported-compiler \
    -DCMAKE_CUDA_HOST_COMPILER=/usr/bin/g++-12"

RUN python3.11 -m pip wheel \
    --no-cache-dir \
    --no-binary llama-cpp-python \
    --wheel-dir=/wheels \
    "llama-cpp-python==${LLAMA_CPP_PYTHON_VERSION}"

# ============================================================
# Vulkan (AMD / Intel / any Vulkan-capable GPU) builder
# Builds llama_cpp_python with Vulkan compute backend.
# Works on RDNA1/2/3, GCN, Intel Arc, and more.
# ============================================================
FROM ubuntu:22.04 AS llama-builder-vulkan
ARG LLAMA_CPP_PYTHON_VERSION

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /build
ADD dockerfile_scripts/install_py11.sh dockerfile_scripts/install_py11.sh
RUN ./dockerfile_scripts/install_py11.sh
# Vulkan headers + glslang (shader compiler) are build-time only
RUN apt-get install -y --no-install-recommends \
        python3.11-dev \
        cmake build-essential ninja-build git \
        libgomp1 \
        libvulkan-dev glslang-tools \
    && rm -rf /var/lib/apt/lists/*

RUN python3.11 -m pip install --no-cache-dir --upgrade pip setuptools wheel

ENV CMAKE_ARGS="-DGGML_VULKAN=ON -DGGML_NATIVE=OFF"

RUN python3.11 -m pip wheel \
    --no-cache-dir \
    --no-binary llama-cpp-python \
    --wheel-dir=/wheels \
    "llama-cpp-python==${LLAMA_CPP_PYTHON_VERSION}"

# ============================================================
# CPU / ARM runtime
# ============================================================
FROM ubuntu:22.04 AS runtime-cpu

ARG CCB_DB_NAME=ccb
ARG CCB_DB_USER=ccbuser
ARG CCB_DB_PASS=ccbpass

ENV CCB_DB_NAME=${CCB_DB_NAME}
ENV CCB_DB_USER=${CCB_DB_USER}
ENV CCB_DB_PASS=${CCB_DB_PASS}
ENV DEBIAN_FRONTEND=noninteractive
ENV AA_DOCKER_ENV=1

WORKDIR /app

ADD dockerfile_scripts/install_deps.sh dockerfile_scripts/install_deps.sh
RUN ./dockerfile_scripts/install_deps.sh
ADD dockerfile_scripts/install_py11.sh dockerfile_scripts/install_py11.sh
RUN ./dockerfile_scripts/install_py11.sh
ADD dockerfile_scripts/pgsql dockerfile_scripts/pgsql
RUN ./dockerfile_scripts/pgsql/install.sh
ADD dockerfile_scripts/install_frpc.sh dockerfile_scripts/install_frpc.sh
RUN ./dockerfile_scripts/install_frpc.sh
RUN apt-get autoclean
ADD dockerfile_scripts/entrypoint.sh dockerfile_scripts/entrypoint.sh

ENV DEBIAN_FRONTEND=dialog

# Install llama_cpp_python from the CPU builder wheel
COPY --from=llama-builder-cpu /wheels /wheels
RUN python3 -m pip install --no-cache-dir --upgrade pip setuptools wheel \
    && python3 -m pip install --no-cache-dir --no-index --find-links=/wheels llama-cpp-python \
    && python3 -m pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu \
    && rm -rf /wheels \
    && pip cache purge

COPY requirements.txt .
RUN sed -i '/^llama_cpp_python/d' requirements.txt \
    && python3 -m pip install --no-cache-dir -r requirements.txt \
    && python3 -m pip cache purge

COPY context_chat_backend context_chat_backend
COPY main.py .
COPY main_em.py .
COPY config.?pu.yaml .
COPY logger_config*.yaml .
COPY hwdetect.sh .
COPY harp_connect.sh .
COPY supervisord.conf /etc/supervisor/supervisord.conf

ENTRYPOINT ["supervisord", "-c", "/etc/supervisor/supervisord.conf"]

# ============================================================
# CUDA (NVIDIA GPU) runtime
# ============================================================
FROM ${CUDA_RUNTIME_IMAGE} AS runtime-cuda

ARG CCB_DB_NAME=ccb
ARG CCB_DB_USER=ccbuser
ARG CCB_DB_PASS=ccbpass

ENV CCB_DB_NAME=${CCB_DB_NAME}
ENV CCB_DB_USER=${CCB_DB_USER}
ENV CCB_DB_PASS=${CCB_DB_PASS}
ENV DEBIAN_FRONTEND=noninteractive
ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=compute
ENV AA_DOCKER_ENV=1

WORKDIR /app

ADD dockerfile_scripts/install_deps.sh dockerfile_scripts/install_deps.sh
RUN ./dockerfile_scripts/install_deps.sh
ADD dockerfile_scripts/install_py11.sh dockerfile_scripts/install_py11.sh
RUN ./dockerfile_scripts/install_py11.sh
ADD dockerfile_scripts/pgsql dockerfile_scripts/pgsql
RUN ./dockerfile_scripts/pgsql/install.sh
ADD dockerfile_scripts/install_frpc.sh dockerfile_scripts/install_frpc.sh
RUN ./dockerfile_scripts/install_frpc.sh
RUN apt-get autoclean
ADD dockerfile_scripts/entrypoint.sh dockerfile_scripts/entrypoint.sh

ENV DEBIAN_FRONTEND=dialog

# Install llama_cpp_python from the CUDA builder wheel
COPY --from=llama-builder-cuda /wheels /wheels
RUN python3 -m pip install --no-cache-dir --upgrade pip setuptools wheel \
    && python3 -m pip install --no-cache-dir --no-index --find-links=/wheels llama-cpp-python \
    && rm -rf /wheels \
    && pip cache purge

COPY requirements.txt .
RUN sed -i '/^llama_cpp_python/d' requirements.txt \
    && python3 -m pip install --no-cache-dir -r requirements.txt \
    && python3 -m pip cache purge

COPY context_chat_backend context_chat_backend
COPY main.py .
COPY main_em.py .
COPY config.?pu.yaml .
COPY logger_config*.yaml .
COPY hwdetect.sh .
COPY harp_connect.sh .
COPY supervisord.conf /etc/supervisor/supervisord.conf

ENTRYPOINT ["supervisord", "-c", "/etc/supervisor/supervisord.conf"]

# ============================================================
# Vulkan (AMD / Intel / any Vulkan-capable GPU) runtime
# Run with: --device /dev/dri (and optionally --device /dev/kfd for AMD)
# The RADV Mesa driver (mesa-vulkan-drivers) is included and covers
# GCN, RDNA1/2/3 and newer AMD GPUs out of the box.
# ============================================================
FROM ubuntu:22.04 AS runtime-vulkan

ARG CCB_DB_NAME=ccb
ARG CCB_DB_USER=ccbuser
ARG CCB_DB_PASS=ccbpass

ENV CCB_DB_NAME=${CCB_DB_NAME}
ENV CCB_DB_USER=${CCB_DB_USER}
ENV CCB_DB_PASS=${CCB_DB_PASS}
ENV DEBIAN_FRONTEND=noninteractive
ENV AA_DOCKER_ENV=1

WORKDIR /app

ADD dockerfile_scripts/install_deps.sh dockerfile_scripts/install_deps.sh
RUN ./dockerfile_scripts/install_deps.sh
ADD dockerfile_scripts/install_py11.sh dockerfile_scripts/install_py11.sh
RUN ./dockerfile_scripts/install_py11.sh
ADD dockerfile_scripts/pgsql dockerfile_scripts/pgsql
RUN ./dockerfile_scripts/pgsql/install.sh
ADD dockerfile_scripts/install_frpc.sh dockerfile_scripts/install_frpc.sh
RUN ./dockerfile_scripts/install_frpc.sh
RUN apt-get autoclean
ADD dockerfile_scripts/entrypoint.sh dockerfile_scripts/entrypoint.sh

# Install Vulkan runtime + AMD RADV open-source driver
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libvulkan1 mesa-vulkan-drivers \
    && rm -rf /var/lib/apt/lists/*

ENV DEBIAN_FRONTEND=dialog

# Install llama_cpp_python from the Vulkan builder wheel
COPY --from=llama-builder-vulkan /wheels /wheels
RUN python3 -m pip install --no-cache-dir --upgrade pip setuptools wheel \
    && python3 -m pip install --no-cache-dir --no-index --find-links=/wheels llama-cpp-python \
    && rm -rf /wheels \
    && pip cache purge

COPY requirements.txt .
RUN sed -i '/^llama_cpp_python/d' requirements.txt \
    && python3 -m pip install --no-cache-dir -r requirements.txt \
    && python3 -m pip cache purge

COPY context_chat_backend context_chat_backend
COPY main.py .
COPY main_em.py .
COPY config.?pu.yaml .
COPY logger_config*.yaml .
COPY hwdetect.sh .
COPY harp_connect.sh .
COPY supervisord.conf /etc/supervisor/supervisord.conf

ENTRYPOINT ["supervisord", "-c", "/etc/supervisor/supervisord.conf"]

FROM runtime-cpu AS final
