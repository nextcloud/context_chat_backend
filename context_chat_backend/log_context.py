from contextvars import ContextVar

# Holds the current HTTP request ID for correlation across logs
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

