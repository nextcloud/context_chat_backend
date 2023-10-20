FROM python:3.11-bookworm

COPY reqs.txt /
ADD . .

RUN \
  python3 -m pip install -r reqs.txt --no-deps && rm -rf ~/.cache

ENTRYPOINT [
	"python3", "src/main.py",
	"-db", "weaviate",
	"-em", "hugging_face",
	"-lm", "llama"
]
