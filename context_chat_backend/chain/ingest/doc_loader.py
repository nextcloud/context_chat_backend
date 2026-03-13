#
# SPDX-FileCopyrightText: 2023 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#

import asyncio
import logging
import re
import tempfile
from collections.abc import Callable
from io import BytesIO

import docx2txt
from epub2txt import epub2txt
from langchain_unstructured import UnstructuredLoader
from odfdo import Document
from pandas import read_csv, read_excel
from pypdf import PdfReader
from pypdf.errors import FileNotDecryptedError as PdfFileNotDecryptedError
from striprtf import striprtf

from ...types import SourceItem, TaskProcException
from .task_proc import do_ocr, do_transcription

logger = logging.getLogger('ccb.doc_loader')

def _temp_file_wrapper(file: BytesIO, loader: Callable, sep: str = '\n') -> str:
	raw_bytes = file.read()
	with tempfile.NamedTemporaryFile(mode='wb') as tmp:
		tmp.write(raw_bytes)
		docs = loader(tmp.name)

	if isinstance(docs, str) or isinstance(docs, bytes):
		return docs.decode('utf-8', 'ignore') if isinstance(docs, bytes) else docs  # pyright: ignore[reportReturnType]

	return sep.join(d.page_content for d in docs)


# -- LOADERS -- #

def _load_pdf(file: BytesIO) -> str:
	pdf_reader = PdfReader(file)
	return '\n\n'.join([page.extract_text().strip() for page in pdf_reader.pages])


def _load_csv(file: BytesIO) -> str:
	return read_csv(file).to_string(header=False, na_rep='')


def _load_epub(file: BytesIO) -> str:
	return _temp_file_wrapper(file, epub2txt).strip()


def _load_docx(file: BytesIO) -> str:
	return docx2txt.process(file).strip()


def _load_odt(file: BytesIO) -> str:
	return _temp_file_wrapper(file, lambda fp: Document(fp).get_formatted_text()).strip()


def _load_ppt_x(file: BytesIO) -> str:
	return _temp_file_wrapper(file, lambda fp: UnstructuredLoader(fp).load()).strip()


def _load_rtf(file: BytesIO) -> str:
	return striprtf.rtf_to_text(file.read().decode('utf-8', 'ignore')).strip()


def _load_xml(file: BytesIO) -> str:
	data = file.read().decode('utf-8', 'ignore')
	data = re.sub(r'</.+>', '', data)
	return data.strip()


def _load_xlsx(file: BytesIO) -> str:
	return read_excel(file, na_filter=False).to_string(header=False, na_rep='')


def _load_email(file: BytesIO, ext: str = 'eml') -> str | None:
	# NOTE: msg format is not tested
	if ext not in ['eml', 'msg']:
		return None

	# TODO: implement attachment partitioner using unstructured.partition.partition_{email,msg}
	# since langchain does not pass through the attachment_partitioner kwarg
	def attachment_partitioner(
		filename: str,
		metadata_last_modified: None = None,
		max_partition: None = None,
		min_partition: None = None,
	):
		...

	return _temp_file_wrapper(
		file,
		lambda fp: UnstructuredLoader(fp, process_attachments=False).load(),
	).strip()


# -- LOADER FUNCTION MAP -- #

_loader_map = {
	'application/pdf': _load_pdf,
	'application/epub+zip': _load_epub,
	'text/csv': _load_csv,
	'application/vnd.openxmlformats-officedocument.wordprocessingml.document': _load_docx,
	'application/vnd.ms-powerpoint': _load_ppt_x,
	'application/vnd.openxmlformats-officedocument.presentationml.presentation': _load_ppt_x,
	'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': _load_xlsx,
	'application/vnd.oasis.opendocument.spreadsheet': _load_xlsx,
	'application/vnd.ms-excel.sheet.macroEnabled.12': _load_xlsx,
	'application/vnd.oasis.opendocument.text': _load_odt,
	'text/rtf': _load_rtf,
	'application/xml': _load_xml,
	'message/rfc822': _load_email,
	'application/vnd.ms-outlook': _load_email,
}


def decode_source(source: SourceItem) -> str | None:
	io_obj: BytesIO | None = None
	try:
		# .pot files are powerpoint templates but also plain text files,
		# so we skip them to prevent decoding errors
		if source.title.endswith('.pot'):
			return None

		mimetype = source.type
		if mimetype is None:
			return None

		try:
			if mimetype.startswith('image/'):
				return asyncio.run(do_ocr(source.userIds[0], source.file_id))
			if mimetype.startswith('audio/'):
				return asyncio.run(do_transcription(source.userIds[0], source.file_id))
		except TaskProcException as e:
			# todo: convert this to error obj return
			# todo: short circuit all other ocr/transcription files when a fatal error arrives
			# todo:  maybe with a global ttl, with a retryable tag
			logger.warning(f'OCR task failed for source file ({source.reference}): {e}')
			return None
		except ValueError:
			# should not happen
			logger.warning(f'Unexpected ValueError for source file ({source.reference})')
			return None

		if isinstance(source.content, str):
			io_obj = BytesIO(source.content.encode('utf-8', 'ignore'))
		else:
			io_obj = source.content

		if _loader_map.get(mimetype):
			result = _loader_map[mimetype](io_obj)
			return result.encode('utf-8', 'ignore').decode('utf-8', 'ignore')

		return io_obj.read().decode('utf-8', 'ignore')
	except PdfFileNotDecryptedError:
		logger.warning(f'PDF file ({source.reference}) is encrypted and cannot be read')
		return None
	except Exception:
		logger.exception(f'Error decoding source file ({source.reference})', stack_info=True)
		return None
	finally:
		if io_obj is not None:
			io_obj.close()
