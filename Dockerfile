FROM python:3.11-bookworm

VOLUME /app/model_files
VOLUME /app/vector_db_data
ENV VECTORDB_DIR /app/vector_db_data
ENV SENTENCE_TRANSFORMERS_HOME /app/model_files
ENV TRANSFORMERS_CACHE /app/model_files

RUN apt update && apt install -y --no-install-recommends pandoc

WORKDIR /app

COPY schackles schackles
COPY main.py .
COPY config.yaml .
COPY reqs.txt .

RUN python3 -m pip install --no-cache-dir --no-deps -r reqs.txt

CMD ["python3", "main.py"]
