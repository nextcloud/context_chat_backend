# Schackles

## Local Setup (without docker)

1. `python -m venv .venv`
2. `. .venv/bin/activate`
3. `pip install --no-deps -r reqs.txt`
4. `docker-compose -f weaviate-docker-compose.yml up -d`
5. Copy example.env to .env and fill in the variables
6. For using the Llama model as the llm, download a gguf llm model from [Hugging Face](https://huggingface.co/TheBloke/CodeLlama-7B-GGUF#provided-files) and place it in `models/`
7. Configure `config.yaml` for the model name, model type and its parameters (which also includes model file's path and model id as per requirements, see example config)
8. `./main.py -db weaviate -em huggingface -lm llama`
9. [Follow the below steps to register the app in the app ecosystem](#register-as-an-ex-app)

## Local Setup (with docker)

1. `docker build -t schackles .`
2. `docker run --add-host=host.docker.internal:host-gateway -p10034:10034 schackles`
3. If your Nextcloud is running inside a docker container, ensure you have mounted the docker socket inside your container and has the correct permissions for the web server user to have access to it or add the web server to the docker group:
	- for docker compose
	```yaml
	    volumes:
      - /var/run/docker.sock:/tmp/docker.sock:ro
	```
	- for docker container run command
	```
	-v /var/run/docker.sock:/var/run/docker.sock:ro
	```
4. [Follow the below steps to register the app in the app ecosystem](#register-as-an-ex-app)

## Register as an Ex-App

1. Create a manual deploy daemon:
	```
	occ app_api:daemon:register --net host manual_install "Manual Install" manual-install http null <nextcloud url>
	```
2. `occ app_api:app:register schackles manual_install --json-info "{\"appid\":\"schackles\",\"name\":\"Chat With Your Documents Backend\",\"daemon_config_name\":\"manual_install\",\"version\":\"1.0.0\",\"secret\":\"12345\",\"host\":\"host.docker.internal\",\"port\":10034,\"scopes\":{\"required\":[],\"optional\":[]},\"protocol\":\"http\",\"system_app\":0}" --force-scopes`

## Companion app

Install the CWYD PHP app from [here](https://github.com/julien-nc/cwyd)
