#!/bin/sh
# Conditional launcher for the embedding server. The separate process should
# only be started when the builtin backend is selected.
if [ -z "${RAG_BACKEND}" ] || [ "${RAG_BACKEND,,}" = "builtin" ]; then
    exec python3 -u /app/main_em.py
else
    # Keep the supervisor slot occupied without starting the embedder.
    exec tail -f /dev/null
fi
