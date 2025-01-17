#
# SPDX-FileCopyrightText: 2022 MCODING, LLC
# SPDX-FileCopyrightText: 2025 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#

import datetime as dt
import json
import logging
import logging.config
import logging.handlers
from time import gmtime

from ruamel.yaml import YAML

__all__ = ['JSONFormatter', 'setup_logging']

LOG_RECORD_BUILTIN_ATTRS = {
	"args",
	"asctime",
	"created",
	"exc_info",
	"exc_text",
	"filename",
	"funcName",
	"levelname",
	"levelno",
	"lineno",
	"module",
	"msecs",
	"message",
	"msg",
	"name",
	"pathname",
	"process",
	"processName",
	"relativeCreated",
	"stack_info",
	"thread",
	"threadName",
	"taskName",
}


class JSONFormatter(logging.Formatter):
	def __init__(
		self,
		*,
		fmt_keys: dict[str, str] | None = None,
	):
		super().__init__()
		self.fmt_keys = fmt_keys if fmt_keys is not None else {}

	def format(self, record: logging.LogRecord) -> str:
		message = self._prepare_log_dict(record)
		return json.dumps(message, default=str)

	def _prepare_log_dict(self, record: logging.LogRecord):
		always_fields = {
			"message": record.getMessage(),
			"timestamp": dt.datetime.fromtimestamp(
				record.created, tz=dt.UTC,
			).isoformat(),
		}
		if record.exc_info is not None:
			always_fields["exc_info"] = self.formatException(record.exc_info)

		if record.stack_info is not None:
			always_fields["stack_info"] = self.formatStack(record.stack_info)

		message = {
			key: msg_val
			if (msg_val := always_fields.pop(val, None)) is not None
			else getattr(record, val)
			for key, val in self.fmt_keys.items()
		}
		message.update(always_fields)

		for key, val in record.__dict__.items():
			if key not in LOG_RECORD_BUILTIN_ATTRS:
				message[key] = val

		return message


def get_logging_config() -> dict:
	with open('logger_config.yaml') as f:
		try:
			yaml = YAML(typ='safe')
			config: dict = yaml.load(f)
		except Exception as e:
			raise AssertionError('Error: could not load config from logger_config.yaml file') from e

	return config


def setup_logging(config: dict):
	logging.config.dictConfig(config)
	logging.Formatter.converter = gmtime
