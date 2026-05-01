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
from sys import getsizeof

import docx2txt
from epub2txt import epub2txt
from langchain_unstructured import UnstructuredLoader
from odfdo import Document
from pandas import read_csv, read_excel
from pypdf import PdfReader
from pypdf.errors import FileNotDecryptedError as PdfFileNotDecryptedError
from striprtf import striprtf

from ...types import IndexingException, SourceItem, TaskProcClientException, TaskProcException, TaskProcFatalException
from .task_proc import (
	OCR_TASK_TYPE,
	SPEECH_TO_TEXT_TASK_TYPE,
	RetryableException,
	delete_temp_files,
	do_ocr,
	do_transcription,
	is_task_type_available,
	upload_temp_files,
)

logger = logging.getLogger('ccb.doc_loader')
PDF_IMAGES_BATCH_SIZE = 25
PDF_IMAGES_MAX_SIZE = 100 * 1024 * 1024  # 100 MiB in bytes
# todo: cache it across processes?
IS_OCR_AVAILABLE = is_task_type_available(OCR_TASK_TYPE)
IS_STT_AVAILABLE = is_task_type_available(SPEECH_TO_TEXT_TASK_TYPE)

def _temp_file_wrapper(file: BytesIO, loader: Callable, sep: str = '\n') -> str:
	raw_bytes = file.read()
	with tempfile.NamedTemporaryFile(mode='wb') as tmp:
		tmp.write(raw_bytes)
		docs = loader(tmp.name)

	if isinstance(docs, str) or isinstance(docs, bytes):
		return docs.decode('utf-8', 'ignore') if isinstance(docs, bytes) else docs  # pyright: ignore[reportReturnType]

	return sep.join(d.page_content for d in docs)


# -- LOADERS -- #

def _load_pdf(file: BytesIO, source: SourceItem) -> str:
	global IS_OCR_AVAILABLE
	pdf_reader = PdfReader(file)
	output = []

	for page in pdf_reader.pages:
		text = page.extract_text().strip()
		page_ocr_outputs = []

		if IS_OCR_AVAILABLE:
			for i in range(0, len(page.images), PDF_IMAGES_BATCH_SIZE):
				image_files = {}
				for img in page.images[i:i+PDF_IMAGES_BATCH_SIZE]:
					if getsizeof(img.data) > PDF_IMAGES_MAX_SIZE:
						logger.info(
							f'An image {img.name} embedded in a PDF {source.reference}'
							f' exceeds max allowed size of {PDF_IMAGES_MAX_SIZE} bytes'
						)
					image_files[img.name] = img.data

				try:
					file_ids_map = asyncio.run(upload_temp_files(image_files))
				except RetryableException:
					raise
				except Exception as e:
					logger.warning(
						f'Error during uploading an embedded PDF image from {source.reference}: {e}',
						exc_info=e,
					)
					continue

				try:
					ocr_tp_outputs = asyncio.run(do_ocr(source.userIds[0], file_ids_map.values()))  # pyright: ignore[reportArgumentType]
					asyncio.run(delete_temp_files(file_ids_map.values()))  # pyright: ignore[reportArgumentType]
				except TaskProcFatalException as e:
					# task type is not present anymore, flip the task type indicator manually
					# for this complete batched injest process
					logger.warning(
						'The OCR provider disappeared mid-operation, disabling OCR for this batch of'
						f' documents including {source.reference}: {e}'
					)
					IS_OCR_AVAILABLE = False
					break
				except TaskProcException as e:
					logger.warning(f'OCR for embedded images in PDF {source.reference} failed: {e}', exc_info=e)
					continue

				# for each image batch
				page_ocr_outputs += ocr_tp_outputs

		# for each page, append text then its OCR outputs to preserve document order
		output.append(text)
		output += page_ocr_outputs

	return '\n\n'.join(output)


def _load_csv(file: BytesIO, _: SourceItem) -> str:
	return read_csv(file).to_string(header=False, na_rep='')


def _load_epub(file: BytesIO, _: SourceItem) -> str:
	return _temp_file_wrapper(file, epub2txt).strip()


def _load_docx(file: BytesIO, _: SourceItem) -> str:
	return docx2txt.process(file).strip()


def _load_odt(file: BytesIO, _: SourceItem) -> str:
	return _temp_file_wrapper(file, lambda fp: Document(fp).get_formatted_text()).strip()


def _load_ppt_x(file: BytesIO, _: SourceItem) -> str:
	return _temp_file_wrapper(file, lambda fp: UnstructuredLoader(fp).load()).strip()


def _load_rtf(file: BytesIO, _: SourceItem) -> str:
	return striprtf.rtf_to_text(file.read().decode('utf-8', 'ignore')).strip()


def _load_xml(file: BytesIO, _: SourceItem) -> str:
	data = file.read().decode('utf-8', 'ignore')
	data = re.sub(r'</.+>', '', data)
	return data.strip()


def _load_xlsx(file: BytesIO, _: SourceItem) -> str:
	return read_excel(file, na_filter=False).to_string(header=False, na_rep='')


def _load_email(file: BytesIO, _: SourceItem, ext: str = 'eml') -> str | None:
	# NOTE: msg format is not tested
	if ext not in ['eml', 'msg']:
		raise IndexingException(f'Unsupported email format: {ext}')

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


def decode_source(source: SourceItem) -> str:
	'''
	Raises
	------
	IndexingException
	'''

	global IS_OCR_AVAILABLE
	io_obj: BytesIO | None = None
	try:
		# .pot files are powerpoint templates but also plain text files,
		# so we skip them to prevent decoding errors
		if source.title.endswith('.pot'):
			raise IndexingException('PowerPoint template files (.pot) are not supported')

		try:
			if source.type.startswith('image/'):
				if IS_OCR_AVAILABLE:
					return asyncio.run(do_ocr(source.userIds[0], [source.file_id]))[0]
				raise IndexingException(
					f'Image file ({source.reference}) cannot be processed since OCR task type is not present'
				)
			if source.type.startswith('audio/'):
				if IS_STT_AVAILABLE:
					return asyncio.run(do_transcription(source.userIds[0], source.file_id))
				raise IndexingException(
					f'Audio file ({source.reference}) cannot be processed since Speech-to-Text task type is not present'
				)
		except TaskProcFatalException as e:
			logger.warning(
				'The OCR provider disappeared mid-operation, disabling OCR for this batch of'
				f' documents including {source.reference}: {e}'
			)
			IS_OCR_AVAILABLE = False
			raise IndexingException(  # noqa: B904
				f'Image file ({source.reference}) cannot be processed since OCR task type is not present'
			)
		except TaskProcClientException as e:
			logger.warning(f'OCR task failed for source file ({source.reference}): {e}')
			raise IndexingException(f'OCR task failed for source file ({source.reference}): {e}')  # noqa: B904
		except TaskProcException as e:
			logger.warning(f'OCR task failed for source file ({source.reference}), it will be retried: {e}')
			raise IndexingException(  # noqa: B904
				f'OCR task failed for source file ({source.reference}), it will be retried: {e}',
				retryable=True,
			)
		except ValueError:
			# should not happen
			logger.warning(f'Unexpected ValueError for source file ({source.reference})')
			raise IndexingException(f'Unexpected ValueError for source file ({source.reference})')  # noqa: B904

		if isinstance(source.content, str):
			io_obj = BytesIO(source.content.encode('utf-8', 'ignore'))
		else:
			io_obj = source.content

		if _loader_map.get(source.type):
			result = _loader_map[source.type](io_obj)
			return result.encode('utf-8', 'ignore').decode('utf-8', 'ignore').strip()

		return io_obj.read().decode('utf-8', 'ignore').strip()
	except IndexingException:
		raise
	except PdfFileNotDecryptedError as e:
		raise IndexingException('PDF file is encrypted and cannot be read') from e
	except Exception as e:
		raise IndexingException(f'Error decoding source file: {e}') from e
	finally:
		if io_obj is not None:
			io_obj.close()
