#!/usr/bin/env sh

parts=(${APP_VERSION//./ })
repair_filename="repair${parts[0]}$(printf %03d ${parts[1]})_date$(date +%Y%m%d%H%M%S).py"

echo "Generating repair script: $repair_filename"
read -p "Confirm to create the repair script? [Y/n] " confirm
if [[ ! $confirm =~ ^[Yy]*$ ]]; then
	echo "Aborted."
	exit 1
fi

touch "context_chat_backend/repair/$repair_filename"
