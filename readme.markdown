# Schackles

## Setup

1. `python -m venv .venv`
2. `. .venv/bin/activate`
3. `pip install -r reqs.txt`
4. `docker-compose -f weaviate/docker-compose.yml up -d`
5. Download a gguf model from [Hugging Face](https://huggingface.co/TheBloke/CodeLlama-7B-GGUF#provided-files) and place it in `models/`
6. Copy example.env to .env and fill in the variables
7. `flask run -p 9000`

## API

### Embed files into the vector database

POST `/loadFiles`

#### Body (form-data)

- [file] file1
- [string] userId


### Get all vectors for a user (hard limit: 100)

GET `/getVectors`

#### Query

- [string] userId


### Get similar vectors based on the query for a specific user (with default limit of 5)

GET `/getSimilar`

#### Query

- [string] userId
- [string] query
- [int] limit (optional)


### Answer a query based on the context gathered from vector database (default limit of docs from vector db = 5) using a LLM

GET `/ask`

#### Query

- [string] userId
- [string] query
- [int] limit (optional)


### LLM works on the query and then self-asks follow-up questions to get to the correct answer. It uses Google search to get the intermediate results.

GET `/askWithSearch`

#### Query

- [string] query


### TODO: Delete all vectors of the given filenames from the vector database

DELETE `/deleteFiles`

#### Query

- [string] userId
- [list(string)] filenames

