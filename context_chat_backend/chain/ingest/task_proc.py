#
# SPDX-FileCopyrightText: 2026 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#

import asyncio
import json
import logging
import os
from typing import Any, Literal

import niquests
from nc_py_api import AsyncNextcloudApp, NextcloudException
from pydantic import BaseModel, ValidationError

from ...types import TaskProcException, TaskProcFatalException
from ...utils import timed_cache_async

LOGGER = logging.getLogger('ccb.task_proc')
OCR_TASK_TYPE = 'core:image2text:ocr'
SPEECH_TO_TEXT_TASK_TYPE = 'core:audio2text'
CACHE_TTL = 15 * 60  # cache values for 15 minutes
OCP_TASK_PROC_SCHED_RETRIES = 3
OCP_TASK_TIMEOUT = 20 * 60  # 20 mins to wait for a task to complete


class Task(BaseModel):
	id: int
	status: str
	output: dict[str, Any] | None = None


class TaskResponse(BaseModel):
	task: Task


InputShapeType = Literal[
	'Number',
	'Text',
	'Audio',
	'Image',
	'Video',
	'File',
	'Enum',
	'ListOfNumbers',
	'ListOfTexts',
	'ListOfImages',
	'ListOfAudios',
	'ListOfVideos',
	'ListOfFiles',
]

class InputShape(BaseModel):
	name: str
	description: str
	type: InputShapeType


class InputShapeEnum(BaseModel):
	name: str
	value: str


class TaskType(BaseModel):
	name: str
	description: str
	inputShape: dict[str, InputShape]
	inputShapeEnumValues: dict[str, list[InputShapeEnum]]
	inputShapeDefaults: dict[str, str | int | float]
	optionalInputShape: dict[str, InputShape]
	optionalInputShapeEnumValues: dict[str, list[InputShapeEnum]]
	optionalInputShapeDefaults: dict[str, str | int | float]
	outputShape: dict[str, InputShape]
	outputShapeEnumValues: dict[str, list[InputShapeEnum]]
	optionalOutputShape: dict[str, InputShape]
	optionalOutputShapeEnumValues: dict[str, list[InputShapeEnum]]


class TaskTypesResponse(BaseModel):
	types: dict[str, TaskType]



def __try_parse_ocs_response(response: niquests.Response | None) -> dict | str:
	if response is None or response.text is None:
		return 'No response'
	try:
		ocs_response = json.loads(response.text)
		if not (ocs_data := ocs_response.get('ocs', {}).get('data')):
			return response.text
		return ocs_data
	except json.JSONDecodeError:
		return response.text


async def __schedule_task(user_id: str, task_type: str, custom_id: str, task_input: dict) -> Task:
	'''
	Raises
	------
	TaskProcException
	'''
	nc = AsyncNextcloudApp()
	await nc.set_user(user_id)

	for sched_tries in range(OCP_TASK_PROC_SCHED_RETRIES):
		try:
			response = await nc.ocs(
				'POST',
				'/ocs/v2.php/taskprocessing/schedule',
				json={
					'type': task_type,
					'appId': os.getenv('APP_ID', 'context_chat_backend'),
					'customId': f'ccb-{custom_id}',
					'input': task_input,
				},
			)
			try:
				task = TaskResponse.model_validate(response).task
				LOGGER.debug('TaskProcessing task schedule response', extra={
					'task': task,
				})
				return task
			except ValidationError as e:
				raise TaskProcException('Failed to parse TaskProcessing task result') from e
		except NextcloudException as e:
			if e.status_code == niquests.codes.precondition_failed:  # type: ignore[attr-defined]
				raise TaskProcFatalException(
					'Failed to schedule Nextcloud TaskProcessing task:'
					f' No provider of {task_type} is installed on this Nextcloud instance.'
					' Please install a suitable provider from the AI overview:'
					' https://docs.nextcloud.com/server/latest/admin_manual/ai/overview.html.',
				) from e

			if e.status_code == niquests.codes.too_many_requests:  # type: ignore[attr-defined]
				LOGGER.warning(
					'Rate limited during TaskProcessing task scheduling, waiting 30s before retrying',
					extra={
						'task_type': task_type,
						'sched_try': sched_tries,
					},
				)
				await asyncio.sleep(30)
				continue

			ocs_response = __try_parse_ocs_response(e.response)
			if e.status_code // 100 == 4:
				raise TaskProcFatalException(
					f'Failed to schedule TaskProcessing task due to client error: {ocs_response}',
				) from e

			LOGGER.error('NextcloudException during TaskProcessing task scheduling', exc_info=e, extra={
				'task_type': task_type,
				'sched_try': sched_tries,
				'nc_exc_reason': str(e.reason),
				'nc_exc_info': str(e.info),
				'nc_exc_status_code': str(e.status_code),
				'ocs_response': str(ocs_response),
			})
			raise TaskProcException(f'Failed to schedule TaskProcessing task: {ocs_response}') from e
		except TaskProcException:
			raise
		except Exception as e:
			raise TaskProcException(f'Failed to schedule TaskProcessing task: {e}') from e

	raise TaskProcException('Failed to schedule TaskProcessing task, tried 3 times')


async def __get_task_result(user_id: str, task: Task) -> Any:
	nc = AsyncNextcloudApp()
	await nc.set_user(user_id)

	i = 0
	now_waiting_for = 0

	while task.status != 'STATUS_SUCCESSFUL' and task.status != 'STATUS_FAILED' and now_waiting_for < OCP_TASK_TIMEOUT:
		i += 1
		now_waiting_for += 10
		await asyncio.sleep(10)

		try:
			response = await nc.ocs('GET', f'/ocs/v2.php/taskprocessing/task/{task.id}')
		except NextcloudException as e:
			if e.status_code == niquests.codes.too_many_requests:  # type: ignore[attr-defined]
				LOGGER.warning(
					'Rate limited during TaskProcessing task polling, waiting 10s before retrying',
					extra={
						'task_id': task.id,
						'tries_so_far': i,
						'waiting_time': now_waiting_for,
					},
				)
				now_waiting_for += 60
				await asyncio.sleep(60)
				continue
			raise TaskProcException('Failed to poll TaskProcessing task') from e
		except niquests.RequestException as e:
			LOGGER.warning('Ignored error during TaskProcessing task polling', exc_info=e, extra={
				'task_id': task.id,
				'tries_so_far': i,
				'waiting_time': now_waiting_for,
			})
			continue

		try:
			task = TaskResponse.model_validate(response).task
			LOGGER.debug(f'TaskProcessing task poll ({now_waiting_for}s) response', extra={
				'task_id': task.id,
				'tries_so_far': i,
				'waiting_time': now_waiting_for,
				'task': task,
			})
		except ValidationError as e:
			raise TaskProcException('Failed to parse TaskProcessing task result') from e

	if task.status != 'STATUS_SUCCESSFUL':
		raise TaskProcException(
			f'TaskProcessing task id {task.id} failed with status {task.status}'
			f' after waiting {now_waiting_for} seconds',
		)

	if not isinstance(task.output, dict) or 'output' not in task.output:
		raise TaskProcException(f'"output" key not found or invalid in TaskProcessing task result: {task.output}')

	return task.output['output']


async def do_ocr(user_id: str, file_id: int) -> str:
	try:
		task = await __schedule_task(user_id, OCR_TASK_TYPE, str(file_id), {'input': [file_id]})
		output = await __get_task_result(user_id, task)
		if not isinstance(output, list) or len(output) == 0 or not isinstance(output[0], str):
			raise TaskProcException(f'OCR task returned empty or invalid output: {output}')
		return output[0]
	except TaskProcException as e:
		LOGGER.error(f'Failed to perform OCR for file_id {file_id}', exc_info=e)
		raise


async def do_transcription(user_id: str, file_id: int) -> str:
	try:
		task = await __schedule_task(user_id, SPEECH_TO_TEXT_TASK_TYPE, str(file_id), {'input': file_id})
		output = await __get_task_result(user_id, task)
		if not isinstance(output, str) or len(output.strip()) == 0:
			raise TaskProcException(f'Speech-to-text task returned empty or invalid output: {output}')
		return output
	except TaskProcException as e:
		LOGGER.error(f'Failed to perform transcription for file_id {file_id}', exc_info=e)
		raise


@timed_cache_async(CACHE_TTL)
async def __get_task_types() -> TaskTypesResponse:
	'''
	Raises
	------
		TaskProcException
	'''
	nc = AsyncNextcloudApp()

	# NC 33 required for this
	try:
		response = await nc.ocs(
			'GET',
			'/ocs/v2.php/taskprocessing/tasks_consumer/tasktypes',
		)
	except NextcloudException as e:
		raise TaskProcException('Failed to fetch Nextcloud TaskProcessing types') from e

	try:
		task_types = TaskTypesResponse.model_validate(response)
		LOGGER.debug('Fetched task types', extra={
			'task_types': task_types,
		})
	except (KeyError, TypeError, ValidationError) as e:
		raise TaskProcException('Failed to parse Nextcloud TaskProcessing types') from e

	return task_types


@timed_cache_async(CACHE_TTL)
async def is_task_type_available(task_type: str) -> bool:
	try:
		task_types = await __get_task_types()
	except Exception as e:
		LOGGER.warning(f'Failed to fetch task types: {e}', exc_info=e)
		return False
	if task_type not in task_types.types:
		return False
	return True
