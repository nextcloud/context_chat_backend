#
# SPDX-FileCopyrightText: 2023 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#

import logging
import re
import tempfile
from collections.abc import Callable
from typing import BinaryIO

import docx2txt
from epub2txt import epub2txt
from fastapi import UploadFile
from langchain_community.document_loaders.unstructured import UnstructuredFileLoader
from odfdo import Document
from pandas import read_csv, read_excel
from pypdf import PdfReader
from striprtf import striprtf

logger = logging.getLogger('ccb.doc_loader')

def _temp_file_wrapper(file: BinaryIO, loader: Callable, sep: str = '\n') -> str:
	raw_bytes = file.read()
	with tempfile.NamedTemporaryFile(mode='wb', delete=False) as tmp:
		tmp.write(raw_bytes)
		docs = loader(tmp.name)

		if not tmp.delete:
			import os
			os.remove(tmp.name)

	if isinstance(docs, str) or isinstance(docs, bytes):
		return docs.decode('utf-8', 'ignore') if isinstance(docs, bytes) else docs  # pyright: ignore[reportReturnType]

	return sep.join(d.page_content for d in docs)


# -- LOADERS -- #

def _load_pdf(file: BinaryIO) -> str:
	pdf_reader = PdfReader(file)
	return '\n\n'.join([page.extract_text().strip() for page in pdf_reader.pages])


def _load_csv(file: BinaryIO) -> str:
	return read_csv(file).to_string(header=False, na_rep='')


def _load_epub(file: BinaryIO) -> str:
	return _temp_file_wrapper(file, epub2txt).strip()


def _load_docx(file: BinaryIO) -> str:
	return docx2txt.process(file).strip()


def _load_odt(file: BinaryIO) -> str:
	return _temp_file_wrapper(file, lambda fp: Document(fp).get_formatted_text()).strip()


def _load_ppt_x(file: BinaryIO) -> str:
	return _temp_file_wrapper(file, lambda fp: UnstructuredFileLoader(fp).load()).strip()


def _load_rtf(file: BinaryIO) -> str:
	return striprtf.rtf_to_text(file.read().decode('utf-8', 'ignore')).strip()


def _load_xml(file: BinaryIO) -> str:
	data = file.read().decode('utf-8', 'ignore')
	data = re.sub(r'</.+>', '', data)
	return data.strip()


def _load_xlsx(file: BinaryIO) -> str:
	return read_excel(file).to_string(header=False, na_rep='')


def _load_email(file: BinaryIO, ext: str = 'eml') -> str | None:
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
		lambda fp: UnstructuredFileLoader(fp, process_attachments=False).load(),
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


def decode_source(source: UploadFile) -> str | None:
	try:
		# .pot files are powerpoint templates but also plain text files,
		# so we skip them to prevent decoding errors
		if source.headers['title'].endswith('.pot'):
			return None

		mimetype = source.headers['type']
		if mimetype is None:
			return None

		if _loader_map.get(mimetype):
			result = _loader_map[mimetype](source.file)
			source.file.close()
			return result

		result = source.file.read().decode('utf-8', 'ignore')
		source.file.close()
		return result
	except Exception:
		logger.exception(f'Error decoding source file ({source.filename})', stack_info=True)
		return None
	finally:
		source.file.close()  # Ensure file is closed after processing
