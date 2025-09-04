from __future__ import annotations

from typing import Any, Mapping


class RetryableBackendBusy(Exception):
    """Signal that the backend is temporarily busy and the client should retry.

    Optionally carries a small payload that response middleware can use to
    craft endpoint-specific retry responses (e.g., sources_to_retry for
    /loadSources).
    """

    def __init__(self, message: str = "", payload: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.payload: dict[str, Any] = dict(payload or {})
