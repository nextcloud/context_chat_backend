from multiprocessing.queues import Queue

from context_chat_backend.chain import embed_sources
from context_chat_backend.vectordb import BaseVectorDB


def parsing_worker(worker_idx, parsing_taskqueue: Queue):
    from context_chat_backend.controller import vectordb_loader
    db: BaseVectorDB = vectordb_loader.load()

    while True:
        sources, result_queue, config = parsing_taskqueue.get()

        try:
            result = embed_sources(db, config, sources)
        except:
            # log error
            result = False
        finally:
            result_queue.put(result)
