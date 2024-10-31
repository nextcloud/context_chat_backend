import multiprocessing
import os
from multiprocessing.queues import Queue

from context_chat_backend.chain import embed_sources
from context_chat_backend.config_parser import get_config
from context_chat_backend.dyn_loader import VectorDBLoader
from context_chat_backend.vectordb import BaseVectorDB


def parsing_worker(vectordb_loader: VectorDBLoader, parsing_taskqueue: Queue, embedding_taskqueue: Queue):
    db: BaseVectorDB|None = None
    config = None
    worker_name = multiprocessing.current_process().name
    print('##############Start parsing worker %s' % worker_name, flush=True)

    while True:
        sources, result = parsing_taskqueue.get()
        print('[parsing_worker] Received parsing task')
        if db is None:
            db = vectordb_loader.load()
            # dummy request to make sure db is set up
            db.get_objects_from_metadata(
                'dummy',
                'source',
                ['somedumbstuff']
            )
        if config is None:
            config = get_config(os.environ['CC_CONFIG_PATH'])

        try:
            print('[parsing_worker] Running embed_sources')
            embed_sources(db, config, sources, result, embedding_taskqueue)
        except Exception as e:
            print(e)
            # log error
            result['done'].set()# set done flag
