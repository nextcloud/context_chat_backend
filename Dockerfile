# SPDX-FileCopyrightText: 2026 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
ARG UBUNTU_VERSION=24.04
ARG CUDA_VERSION=12.8.2
ARG LLAMA_CPP_PYTHON_VERSION=0.3.23

ARG BASE_IMAGE=ubuntu:${UBUNTU_VERSION}
ARG CUDA_DEVEL_IMAGE=nvidia/cuda:${CUDA_VERSION}-devel-ubuntu${UBUNTU_VERSION}
ARG CUDA_RUNTIME_IMAGE=nvidia/cuda:${CUDA_VERSION}-runtime-ubuntu${UBUNTU_VERSION}

# ============================================================
# CPU / ARM builder
# Builds llama_cpp_python for x86_64 and arm64.
#
# x86_64: AVX2 is the compiled-in SIMD baseline (Haswell / Excavator, ~2013).
#   ggml_cpu_has_*() are compile-time constants, not runtime CPUID checks, so
#   every flag baked in becomes a hard CPU requirement.
# arm64:  GGML_CPU_ARM_ARCH targets armv8.2-a+dotprod+fp16, covering
#   Graviton2+, Cortex-A55+, Ampere Altra, Apple M-series (dev machines).
#   All arm64 CPUs with those extensions since ~2019 are included.
#
# GGML_NATIVE=OFF: no -march=native; host SIMD is not baked in.
# ============================================================
FROM ${BASE_IMAGE} AS llama-builder-cpu
ARG LLAMA_CPP_PYTHON_VERSION

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /build
ADD dockerfile_scripts/install_py11.sh dockerfile_scripts/install_py11.sh
RUN ./dockerfile_scripts/install_py11.sh
# gcc-14: Ubuntu 24.04 ships gcc-13 by default; gcc-14 is used for
# consistency across all builder stages and better C++23 support.
RUN apt-get install -y --no-install-recommends \
        python3.11-dev \
        cmake build-essential ninja-build git \
        gcc-14 g++-14 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN /usr/bin/python3.11 -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install --no-cache-dir --upgrade pip setuptools wheel

ENV CC=gcc-14 CXX=g++-14
# Note: GGML_BACKEND_DL=ON + GGML_CPU_ALL_VARIANTS=ON would be ideal (builds
# per-SIMD .so files selected at runtime), but llama-cpp-python's CMakeLists.txt
# only calls llama_cpp_python_install_target(ggml-cpu), a single target.
# With ALL_VARIANTS, cmake creates ggml-cpu-{sandybridge,haswell,...} targets
# *instead* of ggml-cpu, so that install call is a no-op and none of the variant
# .so files end up in the wheel. arm64 variants are not covered at all.
# Tracked upstream: https://github.com/abetlen/llama-cpp-python/issues/2069
# Until fixed, we compile a single backend with AVX2 as the x86_64 baseline.
# GGML_CPU_ARM_ARCH: sets -march for arm64 only; ignored on x86_64.
ENV CMAKE_ARGS="-DGGML_NATIVE=OFF -DLLAMA_BUILD_TESTS=OFF \
    -DGGML_AVX=ON -DGGML_AVX2=ON \
    -DGGML_CPU_ARM_ARCH=armv8.2-a+dotprod+fp16"

RUN /opt/venv/bin/python -m pip wheel \
    --no-cache-dir \
    --no-binary llama-cpp-python \
    --wheel-dir=/wheels \
    "llama-cpp-python==${LLAMA_CPP_PYTHON_VERSION}"

# ============================================================
# CUDA (NVIDIA) builder
# Builds llama_cpp_python with CUDA support.
# CUDA 12.8 supports up to sm_100 (Blackwell / B100, B200).
# gcc-14 is used for consistency with the other build stages and
# because CUDA 12.6+ accepts gcc-14 natively on Ubuntu 24.04.
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
        gcc-14 g++-14 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN /usr/bin/python3.11 -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install --no-cache-dir --upgrade pip setuptools wheel

# Make the CUDA compat stub visible to the linker for both executables and shared libs
RUN ln -s /usr/local/cuda/lib64/stubs/libcuda.so /usr/local/lib/libcuda.so \
    && ln -s /usr/local/cuda/lib64/stubs/libcuda.so /usr/local/lib/libcuda.so.1
ENV LD_LIBRARY_PATH="/usr/local/lib:/usr/local/cuda/lib64:/usr/local/cuda/lib64/stubs:${LD_LIBRARY_PATH}"
ENV CC=gcc-14 CXX=g++-14

# Real cubins for all shipping GPU generations through Blackwell (sm_100),
# plus one forward-compatible PTX target to keep wheel size manageable.
ENV CMAKE_ARGS="-DGGML_CUDA=ON -DGGML_CUDA_FORCE_MMQ=ON -DGGML_NATIVE=OFF -DLLAMA_BUILD_TESTS=OFF \
    -DGGML_AVX=ON -DGGML_AVX2=ON \
    -DGGML_CPU_ARM_ARCH=armv8.2-a+dotprod+fp16"

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
        gcc-14 g++-14 \
        libgomp1 \
        libvulkan-dev glslc spirv-headers \
    && rm -rf /var/lib/apt/lists/*

RUN /usr/bin/python3.11 -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install --no-cache-dir --upgrade pip setuptools wheel

ENV CC=gcc-14 CXX=g++-14
ENV CMAKE_ARGS="-DGGML_VULKAN=ON -DGGML_NATIVE=OFF -DLLAMA_BUILD_TESTS=OFF \
    -DGGML_AVX=ON -DGGML_AVX2=ON \
    -DGGML_CPU_ARM_ARCH=armv8.2-a+dotprod+fp16"

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
RUN ln -s /usr/local/cuda/lib64/stubs/libcuda.so /usr/local/lib/libcuda.so \
    && ln -s /usr/local/cuda/lib64/stubs/libcuda.so /usr/local/lib/libcuda.so.1
ENV LD_LIBRARY_PATH="/usr/local/lib:/usr/local/cuda/lib64:/usr/local/cuda/lib64/stubs:${LD_LIBRARY_PATH}"

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
