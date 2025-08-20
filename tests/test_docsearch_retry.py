# ruff: noqa: S101

import json
from typing import Any

import httpx
import pytest

from context_chat_backend import startup_tests


class DummyResponse:
    def __init__(self, data: list[Any], status_code: int = 200) -> None:
        self._data = data
        self.status_code = status_code
        self.text = json.dumps(data)

    def json(self) -> list[Any]:
        return self._data


@pytest.mark.asyncio
async def test_verify_deletion_retries_until_empty(monkeypatch, caplog) -> None:
    calls = 0

    async def fake_call(client, method, url, **kwargs):
        nonlocal calls
        calls += 1
        if calls < 2:
            return DummyResponse([{"title": "gone"}])
        return DummyResponse([])

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(startup_tests, "_call", fake_call)
    monkeypatch.setattr(startup_tests.asyncio, "sleep", no_sleep)

    async with httpx.AsyncClient() as client:
        with caplog.at_level("INFO"):
            result = await startup_tests._verify_deletion_with_retry(
                client,
                "http://example.com",
                {},
                {},
                deleted_title="gone",
            )
    assert result is True
    assert calls == 2
    assert "Deletion verified" in caplog.text


@pytest.mark.asyncio
async def test_verify_deletion_logs_error_after_retries(monkeypatch, caplog) -> None:
    calls = 0

    async def fake_call(client, method, url, **kwargs):
        nonlocal calls
        calls += 1
        return DummyResponse([{"title": "still-there"}])

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(startup_tests, "_call", fake_call)
    monkeypatch.setattr(startup_tests.asyncio, "sleep", no_sleep)

    async with httpx.AsyncClient() as client:
        with caplog.at_level("ERROR"):
            result = await startup_tests._verify_deletion_with_retry(
                client,
                "http://example.com",
                {},
                {},
                deleted_title="still-there",
                retries=3,
                initial_delay=0,
            )
    assert result is False
    assert calls == 3
    assert "Deletion verification failed" in caplog.text
