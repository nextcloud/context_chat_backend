# Context Chat

## Install

1. Install two mandatory apps for this app to work as desired in your Nextcloud install: Context Chat app and the AppAPI app
2. You can use the OCS API or the `occ` commands to interact with this app but it recommended to do that through a Text Processing OCP API consumer like the Assitant app.

## Required Apps

Install the AppAPI App from the [App Store](https://apps.nextcloud.com/apps/app_api)
Install the Context Chat App from the [App Store](https://apps.nextcloud.com/apps/context_chat)
Install the Assistant App from the [App Store](https://apps.nextcloud.com/apps/assistant)

## Local Setup (without docker)

1. `python -m venv .venv`
2. `. .venv/bin/activate`
3. `pip install --no-deps -r reqs.txt`
4. Install pandoc from your desired package manager (`# apt install pandoc` for Debian-based systems)
5. Copy example.env to .env and fill in the variables
6. For using the Llama model as the llm, download a gguf llm model from [Hugging Face like the Dolphin Mistral Model](https://huggingface.co/TheBloke/dolphin-2.2.1-mistral-7B-GGUF/resolve/main/dolphin-2.2.1-mistral-7b.Q5_K_M.gguf) and place it in `model_files/` (huggingface provider models are auto downloaded)
7. Configure `config.yaml` for the model name, model type and its parameters (which also includes model file's path and model id as per requirements, see example config)
8. `./main.py`
9. [Follow the below steps to register the app in the app ecosystem](#register-as-an-ex-app)

## Local Setup (with docker)

1. `docker build -t context_chat_backend_dev . -f Dockerfile-dev` (this is a good place to edit the example.env file before building the container)
2. `docker run --add-host=host.docker.internal:host-gateway -p10034:10034 context_chat_backend_dev`
3. Volumes can be mounted for `model_files` and `vector_db_files` if you wish with `-v $(pwd)/model_files:/app/model_files` and similar for vector_db_files
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
2. `make register28`

