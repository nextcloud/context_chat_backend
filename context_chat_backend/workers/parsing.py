from multiprocessing.queues import Queue

from context_chat_backend.chain import embed_sources
from context_chat_backend.vectordb import BaseVectorDB


def parsing_worker(worker_idx, parsing_taskqueue: Queue):
    from context_chat_backend.controller import vectordb_loader
    db: BaseVectorDB = vectordb_loader.load()

    while True:
        sources, result, config = parsing_taskqueue.get()

        try:
            success = embed_sources(db, config, sources)
        except:
            # log error
            success = False
        finally:
            if success:
                result[1].set()# set success flag
            result[0].set()# set done flag
