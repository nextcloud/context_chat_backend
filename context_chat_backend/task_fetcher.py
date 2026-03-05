#
# SPDX-FileCopyrightText: 2026 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#

from enum import Enum
from threading import Thread

from .types import AppRole
from .utils import get_app_role

APP_ROLE = get_app_role()
THREADS = {}
THREADS_STOP_EVENTS = {}


class ThreadType(Enum):
	FILES_INDEXING = 'files_indexing'
	UPDATES_PROCESSING = 'updates_processing'
	REQUEST_PROCESSING = 'request_processing'


def files_indexing_thread():
	...


def updates_processing_thread():
	...


def request_processing_thread():
	...


def start_bg_threads():
	match APP_ROLE:
		case AppRole.INDEXING | AppRole.NORMAL:
			THREADS[ThreadType.FILES_INDEXING] = Thread(
				target=files_indexing_thread,
				name='FilesIndexingThread',
				daemon=True,
			)
			THREADS[ThreadType.UPDATES_PROCESSING] = Thread(
				target=updates_processing_thread,
				name='UpdatesProcessingThread',
				daemon=True,
			)
			THREADS[ThreadType.FILES_INDEXING].start()
			THREADS[ThreadType.UPDATES_PROCESSING].start()
		case AppRole.RP | AppRole.NORMAL:
			THREADS[ThreadType.REQUEST_PROCESSING] = Thread(
				target=request_processing_thread,
				name='RequestProcessingThread',
				daemon=True,
			)
			THREADS[ThreadType.REQUEST_PROCESSING].start()


def stop_bg_threads():
	match APP_ROLE:
		case AppRole.INDEXING | AppRole.NORMAL:
			if (
				ThreadType.FILES_INDEXING not in THREADS
				or ThreadType.UPDATES_PROCESSING not in THREADS
				or ThreadType.FILES_INDEXING not in THREADS_STOP_EVENTS
				or ThreadType.UPDATES_PROCESSING not in THREADS_STOP_EVENTS
			):
				return
			THREADS_STOP_EVENTS[ThreadType.FILES_INDEXING].set()
			THREADS_STOP_EVENTS[ThreadType.UPDATES_PROCESSING].set()
			THREADS[ThreadType.FILES_INDEXING].join()
			THREADS[ThreadType.UPDATES_PROCESSING].join()
			THREADS.pop(ThreadType.FILES_INDEXING)
			THREADS.pop(ThreadType.UPDATES_PROCESSING)
			THREADS_STOP_EVENTS.pop(ThreadType.FILES_INDEXING)
			THREADS_STOP_EVENTS.pop(ThreadType.UPDATES_PROCESSING)
		case AppRole.RP | AppRole.NORMAL:
			if (
				ThreadType.REQUEST_PROCESSING not in THREADS
				or ThreadType.REQUEST_PROCESSING not in THREADS_STOP_EVENTS
			):
				return
			THREADS_STOP_EVENTS[ThreadType.REQUEST_PROCESSING].set()
			THREADS[ThreadType.REQUEST_PROCESSING].join()
			THREADS.pop(ThreadType.REQUEST_PROCESSING)
			THREADS_STOP_EVENTS.pop(ThreadType.REQUEST_PROCESSING)
