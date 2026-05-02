# SPDX-FileCopyrightText: 2026 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Mock STT + OCR ex_app for CCB integration tests.

Fake test files have the structure:
  {magic_bytes}{identifier}\x00{null padding to 50 KB}

The identifier (filename without extension) is used to look up the pre-stored
transcript/OCR text in TRANSCRIPTS. The magic bytes are skipped based on the
detected MIME type so the provider never tries to parse them as text.
"""
import logging
import os
import threading
import traceback
from contextlib import asynccontextmanager
from threading import Event
from time import sleep

import magic as libmagic
from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()

# ruff: noqa: E402
from nc_py_api import AsyncNextcloudApp, NextcloudApp
from nc_py_api.ex_app import AppAPIAuthMiddleware, run_app, set_handlers
from nc_py_api.ex_app.providers.task_processing import TaskProcessingProvider

logging.basicConfig(
	level=logging.INFO,
	format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
LOGGER = logging.getLogger(os.environ.get('APP_ID', 'ccb_test_providers'))
LOGGER.setLevel(logging.DEBUG)

# ---------------------------------------------------------------------------
# Number of magic bytes written before the identifier in each fake file.
# Determined by the generator script (tests/gen_test_files.py).
# ---------------------------------------------------------------------------
MAGIC_LENGTHS: dict[str, int] = {
	'audio/mpeg':           4,   # MP3  0xfffb9000
	'audio/flac':           4,   # fLaC
	'audio/x-m4a':         16,   # ftyp M4A_ box
	'audio/x-hx-aac-adts':  4,   # ADTS AAC
	'audio/x-wav':         16,   # RIFF...WAVEfmt_
	'image/png':           33,   # PNG sig + IHDR chunk
	'image/jpeg':          11,   # JFIF JPEG
	'image/gif':            6,   # GIF89a
	'image/bmp':           54,   # BMP file + DIB header
	'image/tiff':           4,   # TIFF II/MM
	'image/webp':          12,   # RIFF...WEBP
	'image/heic':          16,   # ftyp heic box
}

# ---------------------------------------------------------------------------
# Pre-stored transcripts / OCR results keyed by identifier (= filename stem).
# ---------------------------------------------------------------------------
TRANSCRIPTS: dict[str, str] = {
	# Audio (STT)
	'amazon_rainforest': (
		'The Amazon rainforest spans nine countries in South America '
		'and produces roughly twenty percent of the world oxygen supply.'
	),
	'black_holes': (
		'A black hole is a region of spacetime where gravity is so strong '
		'that nothing, not even light, can escape from it.'
	),
	'continental_drift': (
		'Continental drift is the gradual movement of the Earth landmasses '
		'relative to each other over geological time scales.'
	),
	'fibonacci_sequence': (
		'The Fibonacci sequence is a series of numbers where each number '
		'is the sum of the two preceding ones, starting from zero and one.'
	),
	'jungle_book': (
		'The Jungle Book follows Mowgli, a boy raised by wolves in the Indian jungle, '
		'who must confront the tiger Shere Khan with the help of Baloo and Bagheera.'
	),
	'light_spectrum': (
		'The visible light spectrum consists of wavelengths ranging from '
		'approximately three hundred eighty to seven hundred nanometers.'
	),
	'monsoon_winds': (
		'Monsoon winds are seasonal winds that bring heavy rainfall '
		'to South Asia between June and September each year.'
	),
	'photosynthesis': (
		'Photosynthesis is the process by which plants use sunlight, water, '
		'and carbon dioxide to produce oxygen and energy in the form of sugar.'
	),
	'prime_numbers': (
		'A prime number is a natural number greater than one '
		'that has no positive divisors other than one and itself.'
	),
	'quantum_computing': (
		'Quantum computing uses quantum mechanical phenomena such as '
		'superposition and entanglement to perform calculations.'
	),
	'solar_system': (
		'The solar system consists of the Sun and all objects that orbit it, '
		'including eight planets, dwarf planets, moons, and asteroids.'
	),
	'tcp_ip_overview': (
		'The TCP IP protocol suite is the foundational communication protocol '
		'of the Internet, enabling data exchange across diverse networks.'
	),

	# Image (OCR)
	'book_page': (
		'Chapter One: The Origins of Writing. '
		'Writing emerged independently in several ancient civilizations around five thousand years ago.'
	),
	'diagram_labels': (
		'Figure 1: System Architecture. '
		'Components: Input Layer, Processing Unit, Output Buffer, Storage Module.'
	),
	'invoice_sample': (
		'Invoice No. 10042. Date: 01/05/2026. '
		'Item: Software License. Quantity: 1. Unit Price: 299.00. Total: 299.00.'
	),
	'map_legend': (
		'Legend: Blue = Water bodies. Green = Forest. '
		'Yellow = Agricultural land. Red = Urban area. Scale 1:50000.'
	),
	'newspaper_headline': (
		'Scientists Discover New Method for Carbon Capture Using Algae Bioreactors. '
		'Research published in Nature, April 2026.'
	),
	'product_label': (
		'Organic Green Tea. Net weight 100g. Ingredients: Green tea leaves. '
		'Store in a cool dry place. Best before: 2027.'
	),
	'shop_receipt': (
		'RECEIPT. Store: Central Market. '
		'Items: Rice 2kg x1.50, Bread x0.90, Milk 1L x1.20. Total: 3.60. Thank you.'
	),
	'street_sign': (
		'MARKET STREET. Speed limit 30. '
		'No parking 8am to 6pm Monday to Saturday.'
	),
	'test': "This is a test for Nextcloud's OCR app.",
	'train_schedule': (
		'Departures: Platform 3. '
		'08:14 Express to Amsterdam. 08:32 Regional to Utrecht. 08:55 Intercity to Rotterdam.'
	),
}

STT_PROVIDER_ID = 'ccb_test_providers:stt'
STT_TASK_TYPE_ID = 'core:audio2text'
OCR_PROVIDER_ID = 'ccb_test_providers:ocr'
OCR_TASK_TYPE_ID = 'core:image2text:ocr'

app_enabled = Event()
TRIGGER = Event()
WAIT_INTERVAL = 5
WAIT_INTERVAL_WITH_TRIGGER = 5 * 60


def _fetch_file_header(nc: NextcloudApp, task_id: int, file_id: int) -> bytes:
	"""Fetch only the first 256 bytes of a task file (enough to extract the identifier)."""
	nc._session.init_adapter()
	resp = nc._session.adapter.request(
		'GET',
		f'/ocs/v2.php/taskprocessing/tasks_provider/{task_id}/file/{file_id}',
		headers={'Range': 'bytes=0-255'},
	)
	if resp.status_code not in (200, 206):
		raise Exception(f'Failed to fetch file {file_id} for task {task_id}: HTTP {resp.status_code}')
	return resp.content


def _transcript_for_bytes(raw: bytes) -> str:
	mime = libmagic.from_buffer(raw[:256], mime=True)
	offset = MAGIC_LENGTHS.get(mime)
	if offset is None:
		raise ValueError(f'Unsupported MIME type for fake file: {mime!r}')
	end = raw.index(b'\x00', offset)
	identifier = raw[offset:end].decode('ascii')
	text = TRANSCRIPTS.get(identifier)
	if text is None:
		raise ValueError(f'No transcript registered for identifier: {identifier!r}')
	return text


# ---------------------------------------------------------------------------
# Background worker - handles both task types in one loop
# ---------------------------------------------------------------------------

def background_thread_task():
	nc = NextcloudApp()

	while True:
		if not app_enabled.is_set():
			LOGGER.debug('App is not enabled, sleeping for 5 secs')
			sleep(5)
			continue

		# STT
		try:
			item = nc.providers.task_processing.next_task(
				[STT_PROVIDER_ID], [STT_TASK_TYPE_ID]
			)
			if item and 'task' in item:
				task = item['task']
				try:
					LOGGER.info(f'STT task {task["id"]}')
					raw = _fetch_file_header(nc, task['id'], task['input']['input'])
					transcript = _transcript_for_bytes(raw)
					nc.providers.task_processing.report_result(task['id'], {'output': transcript})
					LOGGER.info(f'STT task {task["id"]} done')
				except Exception as e:
					LOGGER.error(traceback.format_exc())
					try:
						nc.providers.task_processing.report_result(task['id'], None, str(e))
					except Exception:  # noqa: S110
						pass
				continue  # skip wait, poll again immediately
		except Exception as e:
			LOGGER.error(f'Error polling STT: {e}')

		# OCR
		try:
			item = nc.providers.task_processing.next_task(
				[OCR_PROVIDER_ID], [OCR_TASK_TYPE_ID]
			)
			if item and 'task' in item:
				task = item['task']
				try:
					LOGGER.info(f'OCR task {task["id"]}')
					file_ids: list[int] = task['input']['input']
					outputs = [
						_transcript_for_bytes(_fetch_file_header(nc, task['id'], fid))
						for fid in file_ids
					]
					nc.providers.task_processing.report_result(task['id'], {'output': outputs})
					LOGGER.info(f'OCR task {task["id"]} done')
				except Exception as e:
					LOGGER.error(traceback.format_exc())
					try:
						nc.providers.task_processing.report_result(task['id'], None, str(e))
					except Exception:  # noqa: S110
						pass
				continue
		except Exception as e:
			LOGGER.error(f'Error polling OCR: {e}')

		_wait_for_task()


def _wait_for_task(interval: float | None = None):
	global WAIT_INTERVAL, WAIT_INTERVAL_WITH_TRIGGER
	if interval is None:
		interval = WAIT_INTERVAL
	if TRIGGER.wait(timeout=interval):
		WAIT_INTERVAL = WAIT_INTERVAL_WITH_TRIGGER
	TRIGGER.clear()


# ---------------------------------------------------------------------------
# FastAPI app + lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(_app: FastAPI):
	set_handlers(_app, enabled_handler, trigger_handler=trigger_handler)
	nc = NextcloudApp()
	if nc.enabled_state:
		app_enabled.set()
	threading.Thread(target=background_thread_task, daemon=True).start()
	yield


APP = FastAPI(lifespan=lifespan)
APP.add_middleware(AppAPIAuthMiddleware)


async def enabled_handler(enabled: bool, nc: AsyncNextcloudApp) -> str:
	if enabled:
		await nc.providers.task_processing.register(TaskProcessingProvider(
			id=STT_PROVIDER_ID,
			name='CCB Test STT Provider',
			task_type=STT_TASK_TYPE_ID,
			expected_runtime=5,
		))
		await nc.providers.task_processing.register(TaskProcessingProvider(
			id=OCR_PROVIDER_ID,
			name='CCB Test OCR Provider',
			task_type=OCR_TASK_TYPE_ID,
			expected_runtime=5,
		))
		app_enabled.set()
	else:
		await nc.providers.task_processing.unregister(STT_PROVIDER_ID, True)
		await nc.providers.task_processing.unregister(OCR_PROVIDER_ID, True)
		app_enabled.clear()
	return ''


def trigger_handler(provider_id: str):
	TRIGGER.set()


if __name__ == '__main__':
	run_app('main:APP', log_level='info')
