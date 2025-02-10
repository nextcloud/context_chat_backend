# SPDX-FileCopyrightText: 2023 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
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
	@echo "  run             deploy and install Context Chat for Nextcloud"
	@echo "  "
	@echo "  For development of this example use PyCharm run configurations. Development is always set for last Nextcloud."
	@echo "  First run 'Context Chat' and then 'make manual_register', after that you can use/debug/develop it and easy test."
	@echo "  "
	@echo "  register        perform registration of running 'Context Chat' into the 'manual_install' deploy daemon."

#.PHONY: build-push
#build-push:
#	docker login ghcr.io
#	docker buildx build --push --platform linux/arm64/v8,linux/amd64 --tag ghcr.io/nextcloud/context_chat_backend:4.0.7 --tag ghcr.io/nextcloud/context_chat_backend:latest .

.PHONY: run
run:
	docker exec master-nextcloud-1 sudo -u www-data php occ app_api:app:unregister context_chat_backend --silent --force || true
	docker exec master-nextcloud-1 sudo -u www-data php occ app_api:app:register context_chat_backend \
		--force-scopes \
		--info-xml https://raw.githubusercontent.com/nextcloud/context_chat_backend/master/appinfo/info.xml

.PHONY: register
register:
	docker exec master-nextcloud-1 sudo -u www-data php occ app_api:app:unregister context_chat_backend --silent || true
	docker exec master-nextcloud-1 sudo -u www-data php occ app_api:app:register context_chat_backend manual_install --json-info \
  "{\"id\":\"context_chat_backend\",\"name\":\"Context Chat Backend\",\"daemon_config_name\":\"manual_install\",\"version\":\"4.0.7\",\"secret\":\"12345\",\"port\":10034,\"scopes\":[],\"system\":0}" \
  --force-scopes --wait-finish
