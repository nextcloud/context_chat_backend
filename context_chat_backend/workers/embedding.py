from multiprocessing.queues import Queue

from context_chat_backend.chain.ingest.injest import vectordb_lock
from context_chat_backend.vectordb import BaseVectorDB


def embedding_worker(worker_idx, embedding_taskqueue: Queue):
    from context_chat_backend.controller import vectordb_loader
    db: BaseVectorDB
    while True:
        user_id, split_documents, result = embedding_taskqueue.get()
        if not db:
            db: BaseVectorDB = vectordb_loader.load()

        with vectordb_lock:
            try:
                user_client = db.get_user_client(user_id)
                count = len(user_client.add_documents(split_documents))
            except:
                count = 0

        if count == len(split_documents):
            result[1].set() # set success flag
        result[0].set()# set done flag
