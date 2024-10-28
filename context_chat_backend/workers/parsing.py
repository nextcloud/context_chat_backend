import os
from multiprocessing.queues import Queue

from context_chat_backend.chain import embed_sources
from context_chat_backend.config_parser import get_config
from context_chat_backend.vectordb import BaseVectorDB


def parsing_worker(worker_idx, parsing_taskqueue: Queue):
    from context_chat_backend.controller import vectordb_loader
    db: BaseVectorDB|None = None
    config = None

    while True:
        sources, result = parsing_taskqueue.get()
        print('[parsing_worker] Received parsing task')

        if db is None:
            db = vectordb_loader.load()
        if config is None:
            config = get_config(os.environ['CC_CONFIG_PATH'])

        try:
            print('[parsing_worker] Running embed_sources')
            success = embed_sources(db, config, sources)
        except Exception as e:
            print(e)
            # log error
            success = False
        finally:
            if success:
                result[1].set()# set success flag
            result[0].set()# set done flag
