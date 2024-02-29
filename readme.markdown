
  
  

# Context Chat

  

> [!WARNING]

> This is a beta software. Expect breaking changes.

 > [INFO]
 > A fully working manually example with cuda 11.8 is at the end of this readme

## Simple Install

  

  

  

1. Install three mandatory apps for this app to work as desired in your Nextcloud install from the "Apps" page:

- AppAPI (>= v2.0.3): https://apps.nextcloud.com/apps/app_api

- Context Chat (>= 1.1.0): https://apps.nextcloud.com/apps/context_chat

- Assistant: https://apps.nextcloud.com/apps/assistant (The OCS API or the `occ` commands can also be used to interact with this app but it recommended to do that through a Text Processing OCP API consumer like the Assitant app.)

2. Install this backend app (Context Chat Backend: https://apps.nextcloud.com/apps/context_chat_backend) from the "External Apps" page

  
  

3. Start using Context Chat from the Assistant UI

  

  

  

> [!NOTE]

  

> See [AppAPI's deploy daemon configuration](#configure-the-appapis-deploy-daemon)

  

> For GPU Support:

  

> Ensure docker is installed and the Nextcloud's web server user has access to `/var/run/docker.sock`, the docker socket.

  

> Mount the docker.sock in the Nextcloud container if you happen to use a containerized install of Nextcloud and ensure correct permissions for the web server user to access it.

  

> See 4th point in [Complex Install (with docker)](#complex-install-with-docker) on how to do this

  
  
  

## Complex Install (without docker)

  

  

1.  `python -m venv .venv`

  

2.  `. .venv/bin/activate`

  

3. For using CPU: `pip install --no-deps -r reqs.txt` | or | Using GPU with CUDA: `pip install --no-deps -r requirements_cuda.txt`

  

5. Install pandoc from your desired package manager (`# apt install pandoc` for Debian-based systems)

  

6. Copy example.env to .env and fill in the variables

  

7. Configure `config.yaml`  `(or config_cuda.yaml using gpu and replace config.yaml with it)` for the model name, model type and its parameters (which also includes model file's path and model id as per requirements, see example config)

  

8.  `./main.py`

  

9. [Follow the below steps to register the app in the app ecosystem](#register-as-an-ex-app)

  

## Complex Install (with docker)

  

  

1. CPU: `docker build -t context_chat_backend_dev . -f Dockerfile.dev` |**or**| For GPU Acceleration with CUDA 11.8: `docker build -t context_chat_backend_dev . -f Dockerfile_CUDA11.8` |**or**| For GPU Acceleration with CUDA 12.3: `docker build -t context_chat_backend_dev . -f Dockerfile_CUDA12.3` (this is a good place to edit the example.env file before building the container)

  

2.  `docker run --add-host=host.docker.internal:host-gateway -p10034:10034 context_chat_backend_dev`

  

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

  
  

## Manual Install (without docker)

  

  

1.  `python -m venv .venv`

  

2.  `. .venv/bin/activate`

  

3. For using CPU: `pip install --no-deps -r reqs.txt` | or | Using GPU with CUDA: `pip install --no-deps -r requirements_cuda.txt`

  

5. Install pandoc from your desired package manager (`# apt install pandoc` for Debian-based systems)

  

6. Copy example.env to .env and fill in the variables

  

7. Configure `config.yaml`  `(or config_cuda.yaml using gpu and replace config.yaml with it)` for the model name, model type and its parameters (which also includes model file's path and model id as per requirements, see example config)

  

8.  `./main.py`

  

9. [Follow the below steps to register the app in the app ecosystem](#register-as-an-ex-app)

  

  

## Manual Install (with docker)

1. `docker build -t context_chat_backend_dev . -f Dockerfile`
2. `docker run --env-file example.env --add-host=host.docker.internal:host-gateway -p10034:10034 context_chat_backend_dev` (this is a good place to edit the example.env file before running the container)
  

1.  CPU: `docker build -t context_chat_backend_dev . -f Dockerfile.dev` |**or**| For GPU Acceleration with CUDA 11.8: `docker build -t context_chat_backend_dev . -f Dockerfile_CUDA11.8` |**or**| For GPU Acceleration with CUDA 12.3: `docker build -t context_chat_backend_dev . -f Dockerfile_CUDA12.3` (this is a good place to edit the example.env file before building the container)

2.  `docker run --add-host=host.docker.internal:host-gateway -p10034:10034 context_chat_backend_dev`

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

"{\"appid\":\"context_chat_backend\",\"name\":\"Context Chat Backend\",\"daemon_config_name\":\"manual_install\",\"version\":\"1.1.1\",\"secret\":\"12345\",\"port\":10034,\"scopes\":[],\"system_app\":0}" \

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

  
  

## A fully working GPU Example with cuda 11.8

**1. Build the image**

```
cd /your/path/to/the/cloned/repository

docker build --no-cache -f Dockerfile_CUDA11.8 -t context_chat_backend_dev:11.8 .

```

- ***Parameter explanation:***

`--no-cache`

Tells Docker to build the image without using any cache from previous builds.

`-f Dockerfile_CUDA11.8`

The `-f` or `--file` option specifies the name of the Dockerfile to use for the build. In this case, `Dockerfile_CUDA11.8`

`-t context_chat_backend_dev:11.8`

The `-t` or `--tag` option allows you to name and optionally tag your image, so you can refer to it later.
In this case we name it `context_chat_backend_dev`with the specified version `11.8`

`.`
This final argument specifies the build context to the Docker daemon. In most cases, it's the path to a directory containing the Dockerfile and any other files needed for the build. Using `.` means "use the current directory as the build context."

**2. Run the image**


```
Hint:
Adjust the example.env to your needs so that it fits your environment
```

```

docker run -v ./config_cuda.yaml:/app/config.yaml -v ./context_chat_backend:/app/context_chat_backend -v /var/run/docker.sock:/var/run/docker.sock --env-file example.env -p10034:10034 -e CUDA_VISIBLE_DEVICES=0 -v ./persistent_storage:/app/persistent_storage --gpus=all context_chat_backend_dev:11.8

```

- ***Parameter explanation:***
	
	`-v ./config_cuda.yaml:/app/config.yaml`

	Mounts the config_cuda.yaml which will be used inside the running image

	`-v ./context_chat_backend:/app/context_chat_backend`

	Mounts the context_chat_backend into the docker image

	`-v /var/run/docker.sock:/var/run/docker.sock`

	Mounts the Docker socket file from the host into the container. This is done to allow the Docker client running inside the container to communicate with the Docker daemon on the host, essentially controlling Docker and GPU from within the container.

	`-v ./persistent_storage:/app/persistent_storage`

	Mounts the persistent storage into the docker instance to keep downloaded models stored for the future.

	`--env-file example.env`

	Specifies an environment file named example.env to load environment variables from. Please adjust it for your needs.

	`-p 10034:10034`

	This publishes a container's port (10034) to the host (10034). Please align it with your environment file

	`-e CUDA_VISIBLE_DEVICES=0`

	Used to limit which GPUs are visible to CUDA applications running in the container. In this case, it restricts visibility to only the first GPU.

	`--gpus all`

	Grants the container access to all GPUs available on the host. This is crucial for running GPU-accelerated applications inside the container.

	`context_chat_backend_dev:11.8`

	Specifies the image to use for creating the container. In this case we have build the image in 1.) with the specified tag

**3. Register context_chat_backend**
```
cd /var/www/<your_nextcloud_instance_webroot> # For example /var/www/nextcloud/

sudo -u www-data php occ app_api:app:unregister context_chat_backend

sudo -u www-data php occ app_api:app:register \
    context_chat_backend \
    manual_install \
    --json-info "{\"appid\":\"context_chat_backend\",\
                  \"name\":\"Context Chat Backend\",\
                  \"daemon_config_name\":\"manual_install\",\
                  \"version\":\"1.1.1\",\
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
