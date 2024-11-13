# Nextcloud Assistant Context Chat Backend

> [!NOTE]
> This is a beta software. Expect breaking changes.
>
> Be mindful to install the backend before the Context Chat php app (Context Chat php app would sends all the user-accessible files to the backend for indexing in the background. It is not an issue even if the request fails to an uninitialised backend since those files would be tried again in the next background job run.)
>
> The HTTP request timeout is 50 minutes for all requests and can be changed with the `request_timeout` app config for the php app `context_chat` using the occ command (`occ config:app:set context_chat request_timeout --value=3000`, value is in seconds). The same also needs to be done for docker socket proxy. See [Slow responding ExApps](https://github.com/cloud-py-api/docker-socket-proxy?tab=readme-ov-file#slow-responding-exapps)
>
> An end-to-end example on how to build and register the backend manually (with CUDA) is at the end of this readme
>
> See the [NC Admin docs](https://docs.nextcloud.com/server/latest/admin_manual/ai/app_context_chat.html) for requirements and known limitations.

## Simple Install

Install the given apps for Context Chat to work as desired **in the given order**:
- [AppAPI from the Apps page](https://apps.nextcloud.com/apps/app_api)
- [Context Chat Backend (same major and minor version as Context Chat app below) from the External Apps page](https://apps.nextcloud.com/apps/context_chat_backend)
- [Context Chat (same major and minor version as the backend) from the Apps page](https://apps.nextcloud.com/apps/context_chat)
- [Assistant from the Apps page](https://apps.nextcloud.com/apps/assistant). The OCS API or the `occ` commands can also be used to interact with this app but it recommended to do that through a Task Processing OCP API consumer like the Assistant app, which is also the officially supported universal UI for all the AI providers.
- Text2Text Task Processing Provider like [llm2 from the External Apps page](https://apps.nextcloud.com/apps/llm2) or [integration_openai from the Apps page](https://apps.nextcloud.com/apps/integration_openai)

> [!NOTE]
> See [AppAPI's deploy daemon configuration](#configure-the-appapis-deploy-daemon)
>
> For GPU Support: enable gpu support in the Deploy Daemon's configuration (Admin settings -> AppAPI)

> [!IMPORTANT]
> To avoid task processing execution delay, setup at 4 background job workers in the main server (where Nextcloud is installed). The setup process is documented here: https://docs.nextcloud.com/server/latest/admin_manual/ai/overview.html#improve-ai-task-pickup-speed

## Complex Install (without docker)

0. Install the required apps from [Simple Install](#simple-install) other than Context Chat Backend and setup background job workers
1. `python -m venv .venv`
2. `. .venv/bin/activate`
3. `pip install --upgrade pip setuptools wheel`
4. Install requirements `pip install -r requirements.txt`
5. Copy example.env to .env and fill in the variables
6. Ensure the config file at `persistent_storage/config.yaml` points to the correct config file (cpu vs gpu). If you're unsure, delete it. It will be recreated upon launching the application. The default is to point to the gpu config.
7. Configure `persistent_storage/config.yaml` for the model name, model type and its parameters (which also includes model file's path and model id as per requirements, see example config)
8. Setup postgresql externally or use `dockerfile_scripts/pgsql/install.sh` to install it on a Debian-family system.
9. Set the env var `EXTERNAL_DB` or the `connection` key in the `pgvector` config to the postgresql connection string if you're using an external database.
10. Start the database (see `dockerfile_scripts/pgsql/setup.sh` for an example)
11. `./main.py`
12. [Follow the below steps to register the app in the app ecosystem](#register-as-an-ex-app)

## Complex Install (with docker)

0. Install the required apps from [Simple Install](#simple-install) other than Context Chat Backend and setup background job workers
1. Build the image
    *(this is a good place to edit the example.env file before building the container)*
    `docker build -t context_chat_backend . -f Dockerfile`

2. `docker run -p 10034:10034 context_chat_backend` (Use `--add-host=host.docker.internal:host-gateway` if your nextcloud server runs locally. Adjust `NEXTCLOUD_URL` env var accordingly.)
3. A volume can be mounted for `persistent_storage` if you wish with `-v $(pwd)/persistent_storage:/app/persistent_storage` (In this case, ensure the config file at `$(pwd)/persistent_storage/config.yaml` points to the correct config or just remove it if you're unsure. The default is to point to the gpu config.)
4. [Refer to AppAPI's deploy daemon guide](#configure-the-appapis-deploy-daemon)
5. [Follow the below steps to register the app in the app ecosystem](#register-as-an-ex-app)

## Register as an Ex-App
**1. Create a manual deploy daemon:**
```
occ app_api:daemon:register --net host manual_install "Manual Install" manual-install http <host> <nextcloud_url>
```
`host` will be `localhost` if nextcloud can access localhost or `host.docker.internal` if nextcloud is inside a docker container and the backend app is on localhost.

If nextcloud is inside a container, `--add-host` option would be required by your nextcloud container. [See example above, pt. 2](#complex-install-with-docker)

**2. Register the app using the deploy daemon (be mindful of the port number and the app's version):**
```
occ app_api:app:register context_chat_backend manual_install --json-info \
"{\"appid\":\"context_chat_backend\",\"name\":\"Context Chat Backend\",\"daemon_config_name\":\"manual_install\",\"version\":\"4.0.0-beta4\",\"secret\":\"12345\",\"port\":10034,\"scopes\":[],\"system_app\":0}" \
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
```
volumes:
    - /var/run/docker.sock:/var/run/docker.sock:ro
```

- for docker container, use this option with the `docker run` command
```
-v /var/run/docker.sock:/var/run/docker.sock:ro
```

## Configuration
Configuration resides inside the persistent storage as `config.yaml`. The location is `$APP_PERSISTENT_STORAGE`. By default it would be at `/nc_app_context_chat_backend_data/config.yaml` inside the container.

All the options in the top of the file can be changed normally but for the sections `vectordb`, `embedding`, and `llm`, only the first key from the list is used. The rest is ignored.
Some of the possible options for the loaders/adaptors in the special sections can be found in the provided example config files itself. The rest of the options can be found in langchain's documentation.
For llm->llama as an example, they can be found here: https://api.python.langchain.com/en/latest/llms/langchain_community.llms.llamacpp.LlamaCpp.html

Make sure to restart the app after changing the config file. For docker, this would mean restarting the container (`docker restart nc_app_context_chat_backend` or the container name/id).

This is a file copied from one of the two configurations (config.cpu.yaml or config.gpu.conf) during app startup if `config.yaml` is not already present to the persistent storage. See [Repair section](#repair) on details on the repair step that removes the config if you have a custom config.

## Repair
v2.1.0 introduces repair steps. These run on app startup.

`repair2001_date20240412153300.py` removes the existing config.yaml in the persistent storage for the
hardware detection to run and place a suitable config (based on accelerator detected) in its place.  
To skip this step (or steps in the future), populate the `repair.info` file with the repair file name(s).  
Use the below command inside the container or add the repair filename manually in the repair.info file inside the docker container at `/nc_app_context_chat_backend_data`

`echo repair2001_date20240412153300.py > "$APP_PERSISTENT_STORAGE/repair.info"`

#### How to generate a repair step file
`APP_VERSION` should at least be incremented at the minor level (MAJOR.MINOR.PATCH)

`APP_VERSION="2.1.0" ./genrepair.sh`

## End-to-End Example for Building and Registering the Backend Manually (with CUDA)

**1. Build the image**
```
cd /your/path/to/the/cloned/repository
docker build --no-cache -f Dockerfile -t context_chat_backend_dev:latest .
```

- ***Parameter explanation:***

    `--no-cache`

    Tells Docker to build the image without using any cache from previous builds.

    `-f Dockerfile`

    The *-f* or *--file* option specifies the name of the Dockerfile to use for the build. In this case *Dockerfile*

    `-t context_chat_backend_dev:latest`

    The *-t* or *--tag* option allows you to name and optionally tag your image, so you can refer to it later.
    In this case we name it *context_chat_backend_dev* with the latest version

    `.`

    This final argument specifies the build context to the Docker daemon. In most cases, it's the path to a directory containing the Dockerfile and any other files needed for the build. Using `.` means "use the current directory as the build context."

**2. Run the image**
```
Hint:
Adjust the example.env to your needs so that it fits your environment
```

```
docker run \
    -v ./config.yaml:/app/config.yaml \
    -v ./context_chat_backend:/app/context_chat_backend \
    -v /var/run/docker.sock:/var/run/docker.sock \
    --env-file example.env \
    -p 10034:10034 \
    -e CUDA_VISIBLE_DEVICES=0 \
    -v persistent_storage:/app/persistent_storage \
    --gpus=all \
    context_chat_backend_dev:latest
```

- ***Parameter explanation:***

	`-v ./config.yaml:/app/config.yaml`

	Mounts the config_cuda.yaml which will be used inside the running image

	`-v ./context_chat_backend:/app/context_chat_backend`

	Mounts the context_chat_backend into the docker image

	`-v /var/run/docker.sock:/var/run/docker.sock`

	Mounts the Docker socket file from the host into the container. This is done to allow the Docker client running inside the container to communicate with the Docker daemon on the host, essentially controlling Docker and GPU from within the container.

	`-v persistent_storage:/app/persistent_storage`

	Mounts the persistent storage into the docker instance to keep downloaded models stored for the future.

	`--env-file example.env`

	Specifies an environment file named example.env to load environment variables from. Please adjust it for your needs.

	`-p 10034:10034`

	This publishes a container's port (10034) to the host (10034). Please align it with your environment file

	`-e CUDA_VISIBLE_DEVICES=0`

	Used to limit which GPUs are visible to CUDA applications running in the container. In this case, it restricts visibility to only the first GPU.

	`--gpus all`

	Grants the container access to all GPUs available on the host. This is crucial for running GPU-accelerated applications inside the container.

	`context_chat_backend_dev:latest`

	Specifies the image to use for creating the container. In this case we have build the image in 1.) with the specified tag

**3. Register context_chat_backend**
```
Hint:
Make sure the previous build cuda_backend_dev docker image is running as the next steps will connect to it on the specified port
```

```
cd /var/www/<your_nextcloud_instance_webroot> # For example /var/www/nextcloud/
sudo -u www-data php occ app_api:app:unregister context_chat_backend
sudo -u www-data php occ app_api:app:register \
    context_chat_backend \
    manual_install \
    --json-info "{\"appid\":\"context_chat_backend\",\
                  \"name\":\"Context Chat Backend\",\
                  \"daemon_config_name\":\"manual_install\",\
                  \"version\":\"4.0.0-beta4\",\
                  \"secret\":\"12345\",\
                  \"port\":10034,\
                  \"scopes\":[],\
                  \"system_app\":0}" \
    --force-scopes \
    --wait-finish
```

If successfully registered the output will be like this
```
	ExApp context_chat_backend successfully unregistered.  
	ExApp context_chat_backend deployed successfully.  
	ExApp context_chat_backend successfully registered.
```

And your docker container should show that the application has been enabled:
```
	App enabled  
	TRACE: 172.17.0.1:51422 - ASGI [4] Send {'type': 'http.response.start', 'status': 200, 'headers': '<...>'}  
	INFO: 172.17.0.1:51422 - "PUT /enabled?enabled=1 HTTP/1.1" 200 OK  
	TRACE: 172.17.0.1:51422 - ASGI [4] Send {'type': 'http.response.body', 'body': '<12 bytes>'}  
	TRACE: 172.17.0.1:51422 - ASGI [4] Completed  
	TRACE: 172.17.0.1:51422 - HTTP connection lost  
	INFO: 172.17.0.1:51408 - "POST /init HTTP/1.1" 200 OK  
	TRACE: 172.17.0.1:51408 - ASGI [3] Send {'type': 'http.response.start', 'status': 200, 'headers': '<...>'}  
	TRACE: 172.17.0.1:51408 - ASGI [3] Send {'type': 'http.response.body', 'body': '<2 bytes>'}  
	TRACE: 172.17.0.1:51408 - ASGI [3] Completed
```
