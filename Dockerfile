FROM nvidia/cuda:12.1.1-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update
RUN apt-get install -y software-properties-common
RUN add-apt-repository -y ppa:deadsnakes/ppa
RUN apt-get update
RUN apt-get install -y --no-install-recommends python3.11 python3.11-venv python3-pip vim git pciutils
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1
RUN apt-get -y clean
RUN rm -rf /var/lib/apt/lists/*

ENV NVIDIA_VISIBLE_DEVICES all
ENV NVIDIA_DRIVER_CAPABILITIES compute
ENV DEBIAN_FRONTEND=dialog

# Set working directory
WORKDIR /app

# Copy requirements files
COPY requirements.txt .

# Install requirements
RUN python3 -m pip install --upgrade pip setuptools wheel
RUN python3 -m pip install --no-cache-dir --no-deps -r requirements.txt
RUN python3 -m pip install --no-cache-dir llama_cpp_python --index-url https://github.com/abetlen/llama-cpp-python/releases/download/v0.2.77-cu121/llama_cpp_python-0.2.77-cp311-cp311-linux_x86_64.whl

# Copy application files
COPY context_chat_backend context_chat_backend
COPY main.py .
COPY config.?pu.yaml .
COPY hwdetect.sh .

ENTRYPOINT ["python3", "main.py"]
