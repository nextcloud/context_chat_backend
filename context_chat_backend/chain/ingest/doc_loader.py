import re
import tempfile
from collections.abc import Callable
from logging import error as log_error
from typing import BinaryIO

from fastapi import UploadFile
from langchain_community.document_loaders import (
	UnstructuredEmailLoader,
	UnstructuredPowerPointLoader,
)
from pandas import read_csv, read_excel
from pypandoc import convert_text
from pypdf import PdfReader


def _temp_file_wrapper(file: BinaryIO, loader: Callable, sep: str = '\n') -> str:
	raw_bytes = file.read()
	tmp = tempfile.NamedTemporaryFile(mode='wb')
	tmp.write(raw_bytes)

	docs = loader(tmp.name)

	tmp.close()
	if not tmp.delete:
		import os
		os.remove(tmp.name)

	return sep.join(d.page_content for d in docs)


# -- LOADERS -- #

def _load_pdf(file: BinaryIO) -> str:
	pdf_reader = PdfReader(file)
	return '\n\n'.join([page.extract_text().strip() for page in pdf_reader.pages])


def _load_csv(file: BinaryIO) -> str:
	return read_csv(file).to_string(header=False, na_rep='')


def _load_epub(file: BinaryIO) -> str:
	return convert_text(str(file.read()), 'plain', 'epub', extra_args=["+RTS", "-M4096m", "-RTS"]).strip()


def _load_docx(file: BinaryIO) -> str:
	return convert_text(str(file.read()), 'plain', 'docx', extra_args=["+RTS", "-M4096m", "-RTS"]).strip()


def _load_ppt_x(file: BinaryIO) -> str:
	return _temp_file_wrapper(file, lambda fp: UnstructuredPowerPointLoader(fp).load()).strip()


def _load_rtf(file: BinaryIO) -> str:
	return convert_text(str(file.read()), 'plain', 'rtf', extra_args=["+RTS", "-M4096m", "-RTS"]).strip()


def _load_rst(file: BinaryIO) -> str:
	return convert_text(str(file.read()), 'plain', 'rst', extra_args=["+RTS", "-M4096m", "-RTS"]).strip()


def _load_xml(file: BinaryIO) -> str:
	data = file.read().decode('utf-8')
	data = re.sub(r'</.+>', '', data)
	return data.strip()


def _load_xlsx(file: BinaryIO) -> str:
	return read_excel(file).to_string(header=False, na_rep='')


def _load_odt(file: BinaryIO) -> str:
	return convert_text(str(file.read()), 'plain', 'odt', extra_args=["+RTS", "-M4096m", "-RTS"]).strip()


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
		lambda fp: UnstructuredEmailLoader(fp, process_attachments=False).load(),
	).strip()


def _load_org(file: BinaryIO) -> str:
	return convert_text(str(file.read()), 'plain', 'org', extra_args=["+RTS", "-M4096m", "-RTS"]).strip()


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
	'text/x-rst': _load_rst,
	'application/xml': _load_xml,
	'message/rfc822': _load_email,
	'application/vnd.ms-outlook': _load_email,
	'text/org': _load_org,
}


def decode_source(source: UploadFile) -> str | None:
	try:
		# .pot files are powerpoint templates but also plain text files,
		# so we skip them to prevent decoding errors
		if source.headers.get('title', '').endswith('.pot'):
			return None

		mimetype = source.headers.get('type')
		if mimetype is None:
			return None

		if _loader_map.get(mimetype):
			return _loader_map[mimetype](source.file)

		return source.file.read().decode('utf-8')
	except Exception as e:
		log_error(f'Error decoding source file ({source.filename}): {e}')
		return None
