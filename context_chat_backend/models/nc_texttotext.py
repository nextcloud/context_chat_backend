#
# SPDX-FileCopyrightText: 2024 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
import logging
import time
from typing import Any

import httpx
from langchain_core.callbacks.manager import CallbackManagerForLLMRun
from langchain_core.language_models.llms import LLM
from nc_py_api import NextcloudApp, NextcloudException
from pydantic import BaseModel, ValidationError

from .types import LlmException

logger = logging.getLogger('ccb.models')

def get_model_for(model_type: str, model_config: dict):
	if model_config is None:
		return None

	if model_type == 'llm':
		return CustomLLM()

	return None


class Task(BaseModel):
	id: int
	status: str
	output: dict[str, str] | None = None


class Response(BaseModel):
	task: Task


class CustomLLM(LLM):
	'''A custom chat model that queries Nextcloud's TextToText provider'''

	def _call(
		self,
		prompt: str,
		stop: list[str] | None = None,
		run_manager: CallbackManagerForLLMRun | None = None,
		**kwargs: Any,
	) -> str:
		'''Run the LLM on the given input.

		Override this method to implement the LLM logic.

		Args:
			prompt: The prompt to generate from.
			stop: Stop words to use when generating. Model output is cut off at the
				first occurrence of any of the stop substrings.
				If stop tokens are not supported consider raising NotImplementedError.
			run_manager: Callback manager for the run.
			**kwargs: Arbitrary additional keyword arguments. These are usually passed
				to the model provider API call.

		Returns:
			The model output as a string. Actual completions SHOULD NOT include the prompt.
		'''
		nc = NextcloudApp()

		if kwargs.get('userid') is not None:
			nc.set_user(kwargs['userid'])
		else:
			logger.warning('No user ID provided for Nextcloud TextToText provider')

		sched_tries = 3
		while True:
			try:
				sched_tries -= 1
				if sched_tries <= 0:
					raise LlmException('Failed to schedule Nextcloud TaskProcessing task, tried 3 times')

				response = nc.ocs(
					'POST',
					'/ocs/v1.php/taskprocessing/schedule',
					json={'type': 'core:text2text', 'appId': 'context_chat_backend', 'input': {'input': prompt}},
				)
				break
			except NextcloudException as e:
				if e.status_code == httpx.codes.PRECONDITION_FAILED:
					raise LlmException(
						'Failed to schedule Nextcloud TaskProcessing task: '
						'This app is setup to use a text generation provider in Nextcloud. '
						'No such provider is installed on Nextcloud instance. '
						'Please install integration_openai, llm2 or any other text2text provider.'
					) from e

				if e.status_code == httpx.codes.TOO_MANY_REQUESTS:
					logger.warning('Rate limited during task scheduling, waiting 10s before retrying')
					time.sleep(10)
					continue

				raise LlmException('Failed to schedule Nextcloud TaskProcessing task') from e

		try:
			task = Response.model_validate(response).task
			logger.debug(f'Initial task schedule response: {task}')

			i = 0
			# wait for 30 minutes
			while task.status != 'STATUS_SUCCESSFUL' and task.status != 'STATUS_FAILED' and i < 60 * 6:
				if i < 60 * 3:
					time.sleep(5)
					i += 1
				else:
					# pool every 10 secs in the second half
					time.sleep(10)
					i += 2

				try:
					response = nc.ocs('GET', f'/ocs/v1.php/taskprocessing/task/{task.id}')
				except (
					httpx.RemoteProtocolError,
					httpx.ReadError,
					httpx.LocalProtocolError,
					httpx.PoolTimeout,
				) as e:
					logger.warning('Ignored error during task polling', exc_info=e)
					time.sleep(5)
					i += 1
					continue
				except NextcloudException as e:
					if e.status_code == httpx.codes.TOO_MANY_REQUESTS:
						logger.warning('Rate limited during task polling, waiting 10s before retrying')
						time.sleep(10)
						i += 2
						continue
					raise LlmException('Failed to poll Nextcloud TaskProcessing task') from e

				task = Response.model_validate(response).task
				logger.debug(f'Task poll ({i * 5}s) response: {task}')
		except ValidationError as e:
			raise LlmException('Failed to parse Nextcloud TaskProcessing task result') from e

		if task.status != 'STATUS_SUCCESSFUL':
			raise LlmException('Nextcloud TaskProcessing Task failed')

		if not isinstance(task.output, dict) or 'output' not in task.output:
			raise LlmException('"output" key not found in Nextcloud TaskProcessing task result')

		return task.output['output']

	@property
	def _identifying_params(self) -> dict[str, Any]:
		'''Return a dictionary of identifying parameters.'''
		return {
			# The model name allows users to specify custom token counting
			# rules in LLM monitoring applications (e.g., in LangSmith users
			# can provide per token pricing for their model and monitor
			# costs for the given LLM.)
			'model_name': 'NextcloudTextToTextProvider',
		}

	@property
	def _llm_type(self) -> str:
		'''Get the type of language model used by this chat model. Used for logging purposes only.'''
		return 'nc_texttotext'
