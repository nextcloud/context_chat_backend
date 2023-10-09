vector_dbs = ["weaviate", "faiss"]

__all__ = ["init_db", "vector_dbs"]


def init_db(vector_db: str):
	if vector_db not in vector_dbs:
		raise AssertionError(f"Error: vector_db should be one of {vector_dbs}")

	init_fn = __import__(vector_db, fromlist=["init_db"])

	if init_fn is None:
		raise AssertionError(f"Error: could not load {vector_db}")

	client = init_fn()

	return client

