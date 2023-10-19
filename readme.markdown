# Schackles

## Setup

1. `python -m venv .venv`
2. `. .venv/bin/activate`
3. `pip install -r reqs.txt --no-deps`
4. `docker-compose -f weaviate-docker-compose.yml up -d`
5. Download a gguf model from [Hugging Face](https://huggingface.co/TheBloke/CodeLlama-7B-GGUF#provided-files) and place it in `models/`
6. Copy example.env to .env and fill in the variables
7. `flask run -p 9000`
