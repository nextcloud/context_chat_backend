# Context Chat

## Simple Install

1. Install three mandatory apps for this app to work as desired in your Nextcloud install from the "Apps" page:
	- AppAPI: https://apps.nextcloud.com/apps/app_api
	- Context Chat: https://apps.nextcloud.com/apps/context_chat
	- Assistant: https://apps.nextcloud.com/apps/assistant (The OCS API or the `occ` commands can also be used to interact with this app but it recommended to do that through a Text Processing OCP API consumer like the Assitant app.)
2. Install this backend app (Context Chat Backend: https://apps.nextcloud.com/apps/context_chat_backend) from the "External Apps" page
3. Start using Context Chat from the Assistant UI

> [!NOTE]
> Ensure docker is installed and the Nextcloud's web server user has access to `/var/run/docker.sock`, the docker socket.  
> Mount the docker.sock in the Nextcloud container if you happen to use a containerized install of Nextcloud and ensure correct permissions for the web server user to access it.  
> See 4th point in [Complex Install (with docker)](#complex-install-with-docker) on how to do this

## Complex Install (without docker)

1. `python -m venv .venv`
2. `. .venv/bin/activate`
3. `pip install --no-deps -r reqs.txt`
4. Install pandoc from your desired package manager (`# apt install pandoc` for Debian-based systems)
5. Copy example.env to .env and fill in the variables
6. Configure `config.yaml` for the model name, model type and its parameters (which also includes model file's path and model id as per requirements, see example config)
7. `./main.py`
8. [Follow the below steps to register the app in the app ecosystem](#register-as-an-ex-app)

## Complex Install (with docker)

1. `docker build -t context_chat_backend_dev . -f Dockerfile.dev` (this is a good place to edit the example.env file before building the container)
2. `docker run --add-host=host.docker.internal:host-gateway -p10034:10034 context_chat_backend_dev`
3. Volumes can be mounted for `model_files` and `vector_db_files` if you wish with `-v $(pwd)/model_files:/app/model_files` and similar for vector_db_files
4. If your Nextcloud is running inside a docker container, ensure you have mounted the docker socket inside your container and has the correct permissions for the web server user to have access to it or add the web server to the docker group:
	- for docker compose
	```yaml
	    volumes:
      - /var/run/docker.sock:/tmp/docker.sock:ro
	```
	- for docker container run command
	```
	-v /var/run/docker.sock:/var/run/docker.sock:ro
	```
5. [Follow the below steps to register the app in the app ecosystem](#register-as-an-ex-app)

## Register as an Ex-App

1. Create a manual deploy daemon:
	```
	occ app_api:daemon:register --net host manual_install "Manual Install" manual-install http null <nextcloud url>
	```
2. `make register28`

