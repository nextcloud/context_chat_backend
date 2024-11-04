import multiprocessing
from multiprocessing.queues import Queue

from context_chat_backend.chain.ingest.injest import vectordb_lock
from context_chat_backend.dyn_loader import VectorDBLoader
from context_chat_backend.vectordb import BaseVectorDB


def embedding_worker(vectordb_loader: VectorDBLoader, embedding_taskqueue: Queue):
    db: BaseVectorDB|None = None
    task_count = 0
    worker_name = multiprocessing.current_process().name
    print('##############Start embedding worker %s' % worker_name, flush=True)

    while True:
        task_count += 1
        if task_count > 100:
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
            except Exception as e:
                print(e)
                count = 0

        if count == len(split_documents):
            result['success'].set() # set success flag
        result['done'].set()# set done flag
