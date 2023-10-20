.DEFAULT_GOAL := help

.PHONY: help
help:
	@echo "Python backend for Chat With Your Documents."
	@echo " "
	@echo "Please use \`make <target>\` where <target> is one of"
	@echo " "
	@echo "  Next commands are only for dev environment with nextcloud-docker-dev!"
	@echo "  They should run from the host you are developing on (with activated venv) and not in the container with Nextcloud!"
	@echo "  "
	@echo "  deploy28          deploy example to registered 'docker_dev' for Nextcloud 28"
	@echo "  deploy27          deploy example to registered 'docker_dev' for Nextcloud 27"
	@echo "  "
	@echo "  run28             install CWYD Backend for Nextcloud 28"
	@echo "  run27             install CWYD Backend for Nextcloud 27"
	@echo "  "
	@echo "  For development of this example use PyCharm run configurations. Development is always set for last Nextcloud."
	@echo "  First run 'CWYD Backend' and then 'make manual_register', after that you can use/debug/develop it and easy test."
	@echo "  "
	@echo "  manual_register28 perform registration of running 'CWYD Backend' into the 'manual_install' deploy daemon."
	@echo "  manual_register27 perform registration of running 'CWYD Backend' into the 'manual_install' deploy daemon."

# .PHONY: build-push
# build-push:
# 	docker login ghcr.io
# 	docker buildx build --push --platform linux/arm64/v8,linux/amd64 --tag ghcr.io/nextcloud/cwyd_backend:1.0.3 --tag ghcr.io/nextcloud/cwyd_backend:latest .

.PHONY: deploy28
deploy28:
	docker exec master-nextcloud-1 sudo -u www-data php occ app_api:app:unregister cwyd_backend --silent || true
	docker exec master-nextcloud-1 sudo -u www-data php occ app_api:app:deploy cwyd_backend docker_dev \
		--info-xml https://raw.githubusercontent.com/nextcloud/cwyd_backend/master/appinfo/info.xml

.PHONY: run28
run28:
	docker exec master-nextcloud-1 sudo -u www-data php occ app_api:app:unregister cwyd_backend --silent || true
	docker exec master-nextcloud-1 sudo -u www-data php occ app_api:app:register cwyd_backend docker_dev -e --force-scopes \
		--info-xml https://raw.githubusercontent.com/nextcloud/cwyd_backend/master/appinfo/info.xml

.PHONY: deploy27
deploy27:
	docker exec master-stable27-1 sudo -u www-data php occ app_api:app:unregister cwyd_backend --silent || true
	docker exec master-stable27-1 sudo -u www-data php occ app_api:app:deploy cwyd_backend docker_dev \
		--info-xml https://raw.githubusercontent.com/nextcloud/cwyd_backend/master/appinfo/info.xml

.PHONY: run27
run27:
	docker exec master-stable27-1 sudo -u www-data php occ app_api:app:unregister cwyd_backend --silent || true
	docker exec master-stable27-1 sudo -u www-data php occ app_api:app:register cwyd_backend docker_dev -e --force-scopes \
		--info-xml https://raw.githubusercontent.com/nextcloud/cwyd_backend/master/appinfo/info.xml

.PHONY: manual_register28
manual_register28:
	docker exec master-nextcloud-1 sudo -u www-data php occ app_api:app:unregister cwyd_backend --silent || true
	docker exec master-nextcloud-1 sudo -u www-data php occ app_api:app:register cwyd_backend manual_install --json-info \
  "{\"appid\":\"cwyd_backend\",\"name\":\"Chat With Your Documents Backend\",\"daemon_config_name\":\"manual_install\",\"version\":\"1.0.0\",\"host\":\"host.docker.internal\",\"port\":10034,\"scopes\":{\"required\":[],\"optional\":[]},\"protocol\":\"http\",\"system_app\":0}" \
  -e --force-scopes

.PHONY: manual_register27
manual_register27:
	docker exec master-stable27-1 sudo -u www-data php occ app_api:app:unregister cwyd_backend --silent || true
	docker exec master-stable27-1 sudo -u www-data php occ app_api:app:register cwyd_backend manual_install --json-info \
  "{\"appid\":\"cwyd_backend\",\"name\":\"Chat With Your Documents Backend\",\"daemon_config_name\":\"manual_install\",\"version\":\"1.0.0\",\"host\":\"host.docker.internal\",\"port\":10034,\"scopes\":{\"required\":[],\"optional\":[]},\"protocol\":\"http\",\"system_app\":0}" \
  -e --force-scopes
