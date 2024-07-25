import json
import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ValidationError

from nc_py_api import Nextcloud
from langchain_core.callbacks.manager import CallbackManagerForLLMRun
from langchain_core.language_models.llms import LLM

from context_chat_backend.models import LlmException


def get_model_for(model_type: str, model_config: dict):
	if model_config is None:
		return None

	if model_type == 'llm':
		return CustomLLM()

	return None


class Task(BaseModel):
	id: int
	status: str
	output: Optional[Dict[str, str]] = None


class CustomLLM(LLM):
	"""A custom chat model that queries Nextcloud's TextToText provider
    """

	def _call(
			self,
			prompt: str,
			stop: Optional[List[str]] = None,
			run_manager: Optional[CallbackManagerForLLMRun] = None,
			**kwargs: Any,
	) -> str:
		"""Run the LLM on the given input.

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
        """
		nc = Nextcloud()

		print(json.dumps(prompt))

		response = nc.ocs("POST", "/ocs/v1.php/taskprocessing/schedule", json={
			"type": "core:text2text",
			"appId": "context_chat_backend",
			"input": {
				"input": prompt
			}
		})

		try:
			task = Task.model_validate(response["task"])

			while task.status != 'STATUS_SUCCESSFUL' and task.status != 'STATUS_FAILED':
				time.sleep(5)
				response = nc.ocs("GET", f"/ocs/v1.php/taskprocessing/task/{task.id}")
				task = Task.model_validate(response["task"])
		except ValidationError as e:
			raise LlmException('Failed to parse Nextcloud TaskProcessing task result')

		if task.status == 'STATUS_FAILED':
			raise LlmException('Nextcloud TaskProcessing Task failed')

		return task.output['output']

	@property
	def _identifying_params(self) -> Dict[str, Any]:
		"""Return a dictionary of identifying parameters."""
		return {
			# The model name allows users to specify custom token counting
			# rules in LLM monitoring applications (e.g., in LangSmith users
			# can provide per token pricing for their model and monitor
			# costs for the given LLM.)
			"model_name": "NextcloudTextToTextProvider",
		}

	@property
	def _llm_type(self) -> str:
		"""Get the type of language model used by this chat model. Used for logging purposes only."""
		return "nc_texttotetx"
