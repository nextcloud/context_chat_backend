# SPDX-FileCopyrightText: 2026 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
ARG UBUNTU_VERSION=24.04
ARG CUDA_VERSION=12.8.2
ARG LLAMA_CPP_PYTHON_VERSION=0.3.22

ARG BASE_IMAGE=ubuntu:${UBUNTU_VERSION}
ARG CUDA_DEVEL_IMAGE=nvidia/cuda:${CUDA_VERSION}-devel-ubuntu${UBUNTU_VERSION}
ARG CUDA_RUNTIME_IMAGE=nvidia/cuda:${CUDA_VERSION}-runtime-ubuntu${UBUNTU_VERSION}

# ============================================================
# CPU / ARM builder
# Builds llama_cpp_python for any x86_64 (AVX+, Sandy Bridge 2011+)
# and for arm64 (NEON always available).
# The Ubuntu base image is multi-arch so this stage covers both.
#
# GGML_NATIVE=OFF: no -march=native; the host build machine's SIMD
# capabilities are not baked in. AVX/AVX2/FMA/F16C default to ON in
# llama.cpp cmake and are used when the CPU supports them at runtime
# (the ggml_cpu_has_*() guards). On arm64 those x86 flags are never
# emitted by cmake, so NEON/SVE detection remains intact.
# ============================================================
FROM ${BASE_IMAGE} AS llama-builder-cpu
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

RUN /usr/bin/python3.11 -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install --no-cache-dir --upgrade pip setuptools wheel

ENV CMAKE_ARGS="-DGGML_NATIVE=OFF -DLLAMA_BUILD_TESTS=OFF -DGGML_BACKEND_DL=ON -DGGML_CPU_ALL_VARIANTS=ON"

RUN /opt/venv/bin/python -m pip wheel \
    --no-cache-dir \
    --no-binary llama-cpp-python \
    --wheel-dir=/wheels \
    "llama-cpp-python==${LLAMA_CPP_PYTHON_VERSION}"

# ============================================================
# CUDA (NVIDIA) builder
# Builds llama_cpp_python with CUDA support.
# CUDA 12.8 supports up to sm_100 (Blackwell / B100, B200).
# Ubuntu 24.04 ships gcc-13 which CUDA 12.6+ accepts natively,
# so no compiler pin or --allow-unsupported-compiler is needed.
# ============================================================
FROM ${CUDA_DEVEL_IMAGE} AS llama-builder-cuda
ARG LLAMA_CPP_PYTHON_VERSION

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /build
ADD dockerfile_scripts/install_py11.sh dockerfile_scripts/install_py11.sh
RUN ./dockerfile_scripts/install_py11.sh
RUN apt-get install -y --no-install-recommends \
        python3.11-dev \
        cmake build-essential ninja-build git \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN /usr/bin/python3.11 -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install --no-cache-dir --upgrade pip setuptools wheel

# Make the CUDA compat stub visible to the linker so cuMem* symbols resolve
ENV LD_LIBRARY_PATH="/usr/local/cuda/compat:${LD_LIBRARY_PATH}"

# Real cubins for all shipping GPU generations through Blackwell (sm_100),
# plus one forward-compatible PTX target to keep wheel size manageable.
ENV CMAKE_ARGS="-DGGML_CUDA=ON -DGGML_CUDA_FORCE_MMQ=ON -DGGML_NATIVE=OFF -DLLAMA_BUILD_TESTS=OFF -DGGML_BACKEND_DL=ON -DGGML_CPU_ALL_VARIANTS=ON \
    -DCMAKE_CUDA_ARCHITECTURES=70-real;75-real;80-real;86-real;89-real;90-real;100-real;100-virtual"

RUN /opt/venv/bin/python -m pip wheel \
    --no-cache-dir \
    --no-binary llama-cpp-python \
    --wheel-dir=/wheels \
    "llama-cpp-python==${LLAMA_CPP_PYTHON_VERSION}"

# ============================================================
# Vulkan (AMD / Intel / any Vulkan-capable GPU) builder
# Builds llama_cpp_python with Vulkan compute backend.
# Works on RDNA1/2/3, GCN, Intel Arc, and more.
# ============================================================
FROM ${BASE_IMAGE} AS llama-builder-vulkan
ARG LLAMA_CPP_PYTHON_VERSION

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /build
ADD dockerfile_scripts/install_py11.sh dockerfile_scripts/install_py11.sh
RUN ./dockerfile_scripts/install_py11.sh
# Vulkan headers + glslc (shader compiler) are build-time only
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3.11-dev \
        cmake build-essential ninja-build git \
        libgomp1 \
        libvulkan-dev glslc spirv-headers \
    && rm -rf /var/lib/apt/lists/*

RUN /usr/bin/python3.11 -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install --no-cache-dir --upgrade pip setuptools wheel

ENV CMAKE_ARGS="-DGGML_VULKAN=ON -DGGML_NATIVE=OFF -DLLAMA_BUILD_TESTS=OFF -DGGML_BACKEND_DL=ON -DGGML_CPU_ALL_VARIANTS=ON"

RUN /opt/venv/bin/python -m pip wheel \
    --no-cache-dir \
    --no-binary llama-cpp-python \
    --wheel-dir=/wheels \
    "llama-cpp-python==${LLAMA_CPP_PYTHON_VERSION}"

# ============================================================
# CPU / ARM runtime
# ============================================================
FROM ${BASE_IMAGE} AS runtime-cpu

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
RUN /usr/bin/python3.11 -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install --no-cache-dir --upgrade pip setuptools wheel \
    && /opt/venv/bin/python -m pip install --no-cache-dir --no-index --find-links=/wheels llama-cpp-python \
    && /opt/venv/bin/python -m pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu \
    && rm -rf /wheels \
    && /opt/venv/bin/python -m pip cache purge

COPY requirements.txt .
RUN sed -i '/^llama_cpp_python/d' requirements.txt \
    && /opt/venv/bin/python -m pip install --no-cache-dir -r requirements.txt \
    && /opt/venv/bin/python -m pip cache purge

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
RUN /usr/bin/python3.11 -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install --no-cache-dir --upgrade pip setuptools wheel \
    && /opt/venv/bin/python -m pip install --no-cache-dir --no-index --find-links=/wheels llama-cpp-python \
    && rm -rf /wheels \
    && /opt/venv/bin/python -m pip cache purge

COPY requirements.txt .
RUN sed -i '/^llama_cpp_python/d' requirements.txt \
    && /opt/venv/bin/python -m pip install --no-cache-dir -r requirements.txt \
    && /opt/venv/bin/python -m pip cache purge

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
FROM ${BASE_IMAGE} AS runtime-vulkan

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
RUN /usr/bin/python3.11 -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install --no-cache-dir --upgrade pip setuptools wheel \
    && /opt/venv/bin/python -m pip install --no-cache-dir --no-index --find-links=/wheels llama-cpp-python \
    && rm -rf /wheels \
    && /opt/venv/bin/python -m pip cache purge

COPY requirements.txt .
RUN sed -i '/^llama_cpp_python/d' requirements.txt \
    && /opt/venv/bin/python -m pip install --no-cache-dir -r requirements.txt \
    && /opt/venv/bin/python -m pip cache purge

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
