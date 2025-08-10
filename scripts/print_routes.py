from context_chat_backend.controller import app

for r in app.routes:
    if hasattr(r, 'methods'):
        methods = ','.join(sorted(r.methods))
        print(f"{methods}\t{r.path}")
