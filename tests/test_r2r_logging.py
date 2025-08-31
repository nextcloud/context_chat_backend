# ruff: noqa: S101
import httpx

from context_chat_backend.backends.r2r import R2rBackend


def _backend(response_json: dict[str, str]):
    backend = R2rBackend.__new__(R2rBackend)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response_json)

    transport = httpx.MockTransport(handler)
    backend._client = httpx.Client(
        transport=transport,
        base_url="http://r2r.test",
        headers={"Authorization": "Bearer secret", "X-API-Key": "sekret"},
    )
    return backend


def test_logs_payload_response_and_masks_headers(caplog):
    backend = _backend({"result": "ok"})
    with caplog.at_level("DEBUG"):
        backend._request("POST", "test", json={"foo": "bar"})
    assert 'R2R request payload: {"foo": "bar"}' in caplog.text
    assert 'R2R response body: {"result":"ok"}' in caplog.text
    assert 'authorization: Bearer ***' in caplog.text
    assert 'x-api-key: ***' in caplog.text


def test_logs_form_data(caplog):
    backend = _backend({"result": "ok"})
    with caplog.at_level("DEBUG"):
        backend._request("POST", "test", data={"foo": "bar"})
    assert 'R2R request payload: {"foo": "bar"}' in caplog.text
