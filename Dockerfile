FROM nvidia/cuda:11.8.0-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update
RUN apt-get install -y software-properties-common
RUN add-apt-repository -y ppa:deadsnakes/ppa
RUN apt-get update
RUN apt-get install -y python3.11 python3.11-venv python3-pip cuda-nvcc-11-8 cuda-toolkit-11-8 vim git
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1
RUN python3 -m pip install --upgrade pip setuptools wheel
RUN apt-get install -y --no-install-recommends pandoc
RUN apt-get -y clean
RUN rm -rf /var/lib/apt/lists/*

ENV DEBIAN_FRONTEND=dialog

# Set working directory
WORKDIR /app

# Copy requirements files
COPY requirements.txt .

# Install requirements
RUN python3 -m pip install --no-cache-dir --no-deps -r requirements.txt
RUN CMAKE_ARGS="-DLLAMA_CUBLAS=on -DLLAMA_OPENBLAS=on" python3 -m pip install llama-cpp-python

# Copy application files
COPY context_chat_backend context_chat_backend
COPY main.py .

ENTRYPOINT ["python3", "main.py"]
