from multiprocessing.queues import Queue

from context_chat_backend.chain.ingest.injest import vectordb_lock
from context_chat_backend.vectordb import BaseVectorDB


def embedding_worker(worker_idx, embedding_taskqueue: Queue):
    from context_chat_backend.controller import vectordb_loader
    db: BaseVectorDB|None = None
    count = 0
    print('##############Start embedding worker', flush=True)

    while True:
        count += 1
        if count > 100:
            print('##############Ending embedding worker', flush=True)
            break
        user_id, split_documents, result = embedding_taskqueue.get()
        print('[embedding_worker] Received task from embedding queue')
        if db is None:
            db = vectordb_loader.load()

        print('[embedding_worker] Waiting for vectordb_lock')
        with vectordb_lock:
            print('[embedding_worker] Got vectordb_lock, adding documents to vectordb')
            try:
                user_client = db.get_user_client(user_id)
                count = len(user_client.add_documents(split_documents))
            except:
                count = 0

        if count == len(split_documents):
            result.get('success').set() # set success flag
        result.get('done').set()# set done flag
