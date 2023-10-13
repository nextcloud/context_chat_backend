# Source Generated with Decompyle++
# File: app.cpython-310.pyc (Python 3.10)

from flask import Flask, request, make_response, jsonify

from service import (
	process_files,
	# process_texts,
	get_similar_docs,
	process_query,
	process_search_query,
	delete_files_from_db
)
from utils import value_of

# TODO: remove this eventually
from vectordb import list_vectors

# TODO: use retrievers (langchain)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 256000000


@app.route('/')
def hello():
	return 'Hello, World!'


@app.route('/deleteFiles', methods=['DELETE'])
def delete_files():
	if value_of(request.args.get('userId')) is None:
		return make_response(jsonify({'error': 'No userId provided in the request'}), 400)

	if value_of(request.args.get('filenames')) is None:
		return make_response(jsonify({'error': 'No filenames provided in the request'}), 400)

	# filenames check, should of the form: filename1,filename2,filename3
	filenames = [
		filename.strip()
		for filename in request.args.get('filenames').strip().split(',')
		if filename.strip() != ''
	]

	if len(filenames) == 0:
		return make_response(jsonify({'error': 'No filenames provided in the request'}), 400)

	# TODO: weaviate does not check case of the filename
	return jsonify({'result': delete_files_from_db(
		request.args.get('userId'), filenames
	)})


# TODO: check if vectors for the file already exist and if the modification time is more recent
# TODO: if bpth are true, then delete the vectors and re-embed the file
@app.route('/loadFiles', methods=['POST'])
def load_files():
	if len(request.files) == 0:
		return make_response(jsonify({'error': 'No file found in the request'}), 400)

	if value_of(request.form.get('userId')) is None:
		return make_response(jsonify({'error': 'No userId provided in the request'}), 400)

	return jsonify({'result': process_files(
		request.form.get('userId'), request.files.values()
	)})


# TODO: check if vectors for the file already exist and if the modification time is more recent
# TODO: if bpth are true, then delete the vectors and re-embed the file
@app.route('/loadTexts', methods=['POST'])
def load_texts():
	print('form:', request.form)
	return jsonify({'result': 'success'})


	if value_of(request.form.get('userId')) is None:
		return make_response(jsonify({'error': 'No userId provided in the request'}), 400)

	if len(request.form) < 2:
		return make_response(jsonify({'error': 'No text found in the request'}), 400)

	if value_of(request.form.get('name')) is None \
		or value_of(request.form.get('contents')) is None \
		or value_of(request.form.get('modified')) is None \
		or value_of(request.form.get('mimetype')) is None:
		return make_response(jsonify({'error': 'All fields of text not found in the request'}), 400)

	# source: name, contents
	return jsonify({'result': 'success'})
	# return jsonify({'result': process_files(
	# 	request.form.get('userId'), request.files.values()
	# )})


# TODO: use utils fn here
@app.route('/getSimilar', methods=['GET'])
def get_similar():
	if value_of(request.args.get('query')) is None:
		return make_response(jsonify(
			{'error': 'Request lacks either query or userId or both'}
		), 400)

	if value_of(request.args.get('limit')) is None:
		return jsonify({'result': get_similar_docs(
			request.args.get('userId'),
			request.args.get('query')
		)})

	return jsonify({'result': get_similar_docs(
		request.args.get('userId'),
		request.args.get('query'),
		int(request.args.get('limit'))
	)})


@app.route('/getVectors', methods=['GET'])
def get_vectors():
	if value_of(request.args.get('userId')) is None:
		return make_response(jsonify({'error': 'Request lacks userId'}), 400)

	return jsonify({'result': list_vectors(request.args.get('userId'))})


@app.route('/ask', methods=['GET'])
def ask():
	if value_of(request.args.get('query')) is None:
		return make_response(jsonify(
			{'error': 'Request lacks either query or userId or both'}
		), 400)

	if value_of(request.args.get('limit')) is None:
		out = process_query(
			request.args.get('userId'), request.args.get('query')
		)
		return jsonify({'result': out})

	return jsonify({'result': process_query(
		request.args.get('userId'),
		request.args.get('query'),
		int(request.args.get('limit'))
	)})


@app.route('/askWithSearch', methods=['GET'])
def ask_with_search():
	if value_of(request.args.get('query')) is None:
		return make_response(jsonify({'error': 'Request lacks query'}), 400)

	return jsonify({'result': process_search_query(request.args.get('query'))})

