FROM python:3.11-bookworm

RUN apt update && apt install -y --no-install-recommends pandoc

WORKDIR /app

COPY reqs.txt .
RUN python3 -m pip install --no-cache-dir --no-deps -r reqs.txt

COPY context_chat_backend context_chat_backend
COPY main.py .
COPY config.yaml .

CMD ["python3", "main.py"]
