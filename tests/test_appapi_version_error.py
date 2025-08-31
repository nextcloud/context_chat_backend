import base64

from fastapi import FastAPI
from fastapi.testclient import TestClient

from context_chat_backend.ocs_utils import AppAPIAuthMiddleware


def test_version_mismatch_returns_error(monkeypatch):
    monkeypatch.setenv("APP_ID", "context_chat_backend")
    monkeypatch.setenv("APP_VERSION", "4.4.1")
    monkeypatch.setenv("APP_SECRET", "secret")

    app = FastAPI()
    app.add_middleware(AppAPIAuthMiddleware)

    @app.get("/test")
    def read_root():
        return {"ok": True}

    client = TestClient(app)
    headers = {
        "EX-APP-ID": "context_chat_backend",
        "EX-APP-VERSION": "4.0.3",
        "AUTHORIZATION-APP-API": base64.b64encode(b"user:secret").decode(),
        "OCS-APIRequest": "true",
    }
    resp = client.get("/test", headers=headers)
    assert resp.status_code == 401  # noqa: S101
    assert "Invalid EX-APP-VERSION" in resp.json()["error"]  # noqa: S101
