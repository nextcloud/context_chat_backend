from flask import Flask  # , request, make_response

# TODO: split this in "chain" functions
# from chain.service import (
# 	process_files,
# 	get_similar_docs,
# 	process_query,
# 	process_search_query,
# 	delete_files_from_db
# )
# from utils import value_of

#
# TODO: remove this eventually
# TODO: use retrievers (langchain) or maybe not
# from vectordb.weaviate import list_vectors
#

__all__ = ['app']

# TODO: only use `chain` functions here passing the `vectordb` client, the `em` and `llm` models
# from the config file

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 256000000


@app.route('/')
def _hello():
	"""
	Server check
	"""
	return 'Hello, World!'


# @app.route('/deleteFiles', methods=['DELETE'])
# def delete_files():
# 	if value_of(request.args.get('userId')) is None:
# 		return make_response('No userId provided in the request', 400)

# 	if value_of(request.args.get('filenames')) is None:
# 		return make_response('No filenames provided in the request', 400)

# 	# filenames check, should of the form: filename1,filename2,filename3
# 	filenames = [
# 		filename.strip()
# 		for filename in request.args.get('filenames').strip().split(',')
# 		if filename.strip() != ''
# 	]

# 	if len(filenames) == 0:
# 		return make_response('No filenames provided in the request', 400)

# 	# TODO: weaviate does not check case of the filename
# 	return make_response(delete_files_from_db(
# 		request.args.get('userId'), filenames
# 	))


# # TODO: check if vectors for the file already exist and if the modification
# # time is more recent
# # TODO: if bpth are true, then delete the vectors and re-embed the file
# @app.route('/loadFiles', methods=['POST'])
# def load_files():
# 	if len(request.files) == 0:
# 		return make_response('No file found in the request', 400)

# 	if value_of(request.form.get('userId')) is None:
# 		return make_response('No userId provided in the request', 400)

# 	return make_response(process_files(
# 		request.form.get('userId'), request.files.values()
# 	))


# # TODO: use utils fn here
# @app.route('/getSimilar', methods=['GET'])
# def get_similar():
# 	if value_of(request.args.get('query')) is None:
# 		return make_response('Request lacks either query or userId or both', 400)

# 	if value_of(request.args.get('limit')) is None:
# 		return make_response(get_similar_docs(
# 			request.args.get('userId'),
# 			request.args.get('query')
# 		))

# 	return make_response(get_similar_docs(
# 		request.args.get('userId'),
# 		request.args.get('query'),
# 		int(request.args.get('limit'))
# 	))


# @app.route('/getVectors', methods=['GET'])
# def get_vectors():
# 	if value_of(request.args.get('userId')) is None:
# 		return make_response('Request lacks userId', 400)

# 	return make_response(list_vectors(request.args.get('userId')))


# @app.route('/ask', methods=['GET'])
# def ask():
# 	if value_of(request.args.get('query')) is None:
# 		return make_response('Request lacks either query or userId or both', 400)

# 	if value_of(request.args.get('limit')) is None:
# 		return make_response(process_query(
# 			request.args.get('userId'), request.args.get('query')
# 		))

# 	return make_response(process_query(
# 		request.args.get('userId'),
# 		request.args.get('query'),
# 		int(request.args.get('limit'))
# 	))


# @app.route('/askWithSearch', methods=['GET'])
# def ask_with_search():
# 	if value_of(request.args.get('query')) is None:
# 		return make_response('Request lacks query', 400)

# 	return make_response(process_search_query(request.args.get('query')))

