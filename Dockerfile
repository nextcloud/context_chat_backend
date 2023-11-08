FROM python:3.11-bookworm

# run processes as a non-root user
# RUN useradd -m appuser
# USER appuser

# RUN mkdir -p /home/appuser/app/model_files
# RUN chown appuser:appuser /home/appuser/app/model_files
# ENV TRANSFORMERS_CACHE /home/appuser/app/model_files
# VOLUME /home/appuser/app/model_files

VOLUME /app/model_files
ENV SENTENCE_TRANSFORMERS_HOME /app/model_files

WORKDIR /app

COPY reqs.txt .
COPY schackles schackles
COPY main.py .
COPY config.yaml .
COPY .env .

RUN python3 -m pip install --no-deps -r reqs.txt
RUN rm -rf ~/.cache

CMD ["python3", "main.py", "-db", "weaviate", "-em", "hugging_face"]
