.DEFAULT_GOAL := help

.PHONY: help
help:
	@echo "Python backend for Context Chat."
	@echo " "
	@echo "Please use \`make <target>\` where <target> is one of"
	@echo " "
	@echo "  Next commands are only for dev environment with nextcloud-docker-dev!"
	@echo "  They should run from the host you are developing on (with activated venv) and not in the container with Nextcloud!"
	@echo "  "
	@echo "  deploy28          deploy example to registered 'docker_dev' for Nextcloud 28"
	@echo "  "
	@echo "  run28             install Context Chat for Nextcloud 28"
	@echo "  "
	@echo "  For development of this example use PyCharm run configurations. Development is always set for last Nextcloud."
	@echo "  First run 'Context Chat' and then 'make manual_register', after that you can use/debug/develop it and easy test."
	@echo "  "
	@echo "  register28 perform registration of running 'Context Chat' into the 'manual_install' deploy daemon."

#.PHONY: build-push
#build-push:
#	docker login ghcr.io
#	docker buildx build --push --platform linux/arm64/v8,linux/amd64 --tag ghcr.io/nextcloud/context_chat_backend:0.1.0 --tag ghcr.io/nextcloud/context_chat_backend:latest .

.PHONY: deploy28
deploy28:
	docker exec master-nextcloud-1 sudo -u www-data php occ app_api:app:unregister context_chat_backend --silent || true
	docker exec master-nextcloud-1 sudo -u www-data php occ app_api:app:deploy context_chat_backend docker_dev \
		--info-xml https://raw.githubusercontent.com/nextcloud/context_chat_backend/master/appinfo/info.xml

.PHONY: run28
run28:
	docker exec master-nextcloud-1 sudo -u www-data php occ app_api:app:unregister context_chat_backend --silent || true
	docker exec master-nextcloud-1 sudo -u www-data php occ app_api:app:register context_chat_backend docker_dev \
		--force-scopes \
		--info-xml https://raw.githubusercontent.com/nextcloud/context_chat_backend/master/appinfo/info.xml

.PHONY: register28
register28:
	docker exec master-nextcloud-1 sudo -u www-data php occ app_api:app:unregister context_chat_backend --silent || true
	docker exec master-nextcloud-1 sudo -u www-data php occ app_api:app:register context_chat_backend manual_install --json-info \
  "{\"appid\":\"context_chat_backend\",\"name\":\"Context Chat Backend\",\"daemon_config_name\":\"manual_install\",\"version\":\"0.1.0\",\"secret\":\"12345\",\"host\":\"host.docker.internal\",\"port\":10034,\"scopes\":{\"required\":[],\"optional\":[]},\"protocol\":\"http\",\"system_app\":0}" \
  --force-scopes

