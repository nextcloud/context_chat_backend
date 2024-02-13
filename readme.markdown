# Context Chat

> [!WARNING]
> This is a beta software. Expect breaking changes.

## Simple Install

1. Install three mandatory apps for this app to work as desired in your Nextcloud install from the "Apps" page:
	- AppAPI (>= v2.0.3): https://apps.nextcloud.com/apps/app_api
	- Context Chat (>= 1.1.0): https://apps.nextcloud.com/apps/context_chat
	- Assistant: https://apps.nextcloud.com/apps/assistant (The OCS API or the `occ` commands can also be used to interact with this app but it recommended to do that through a Text Processing OCP API consumer like the Assitant app.)
2. Install this backend app (Context Chat Backend: https://apps.nextcloud.com/apps/context_chat_backend) from the "External Apps" page
3. Start using Context Chat from the Assistant UI

> [!NOTE]
> See [AppAPI's deploy daemon configuration](#configure-the-appapis-deploy-daemon)

## Manual Install (without docker)

1. `python -m venv .venv`
2. `. .venv/bin/activate`
3. `pip install --no-deps -r reqs.txt`
4. Install pandoc from your desired package manager (`# apt install pandoc` for Debian-based systems)
5. Copy example.env to .env and fill in the variables
6. Configure `config.yaml` for the model name, model type and its parameters (which also includes model file's path and model id as per requirements, see example config)
7. `./main.py`
8. [Follow the below steps to register the app in the app ecosystem](#register-as-an-ex-app)

## Manual Install (with docker)

1. `docker build -t context_chat_backend_dev . -f Dockerfile`
2. `docker run --env-file example.env --add-host=host.docker.internal:host-gateway -p10034:10034 context_chat_backend_dev` (this is a good place to edit the example.env file before running the container)
3. Volumes can be mounted for `model_files` and `vector_db_files` if you wish with `-v $(pwd)/model_files:/app/model_files` and similar for vector_db_files
4. If your Nextcloud is running inside a docker container, there are two ways to configure the deploy daemon
5. [Follow the below steps to register the app in the app ecosystem](#register-as-an-ex-app)

(For a dev setup, mount the `context_chat_backend/` folder as a volume and set the uvicorn to reload on change)

## Register as an Ex-App

1. Create a manual deploy daemon:
	```
	occ app_api:daemon:register --net host manual_install "Manual Install" manual-install http <host> <nextcloud url>
	```
	`host` will be `localhost` if nextcloud can access localhost or `host.docker.internal` if nextcloud is inside a docker container and the backend app is on localhost.  
	If nextcloud is inside a container, `--add-host` option would be required by your nextcloud container. [See example above, pt. 2](#complex-install-with-docker)

2. Register the app using the deploy daemon (be mindful of the port number and the app's version):
	```
	occ app_api:app:register context_chat_backend manual_install --json-info \
		"{\"appid\":\"context_chat_backend\",\"name\":\"Context Chat Backend\",\"daemon_config_name\":\"manual_install\",\"version\":\"1.1.0\",\"secret\":\"12345\",\"port\":10034,\"scopes\":[],\"system_app\":0}" \
		--force-scopes --wait-finish
	```

The command to unregister is given below (force is used to also remove apps whose container has been removed)
```
occ app_api:app:unregister context_chat_backend --force
```

## Configure the AppAPI's deploy daemon
Ensure that docker is installed and the default deploy daemon is working in Admin settings -> AppAPI  
Docker socket proxy is the recommended for the deploy daemon. Installation steps can be found here: https://github.com/cloud-py-api/docker-socket-proxy

An alternative method would be to provide the Nextcloud's web server user access to `/var/run/docker.sock`, the docker socket and use deployment configuration in the default deploy daemon of AppAPI.  
Mount the docker.sock in the Nextcloud container if you happen to use a containerized install of Nextcloud and ensure correct permissions for the web server user to access it.  

- for docker compose
```yaml
volumes:
- /var/run/docker.sock:/var/run/docker.sock:ro
```

- for docker container, use this option with the `docker run` command
```
-v /var/run/docker.sock:/var/run/docker.sock:ro
```
