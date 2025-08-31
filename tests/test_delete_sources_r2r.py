# ruff: noqa: S101
import os
import shutil
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

os.environ.setdefault("APP_ID", "context_chat_backend")
os.environ.setdefault("APP_VERSION", "0.0.0")
os.environ.setdefault("RAG_BACKEND", "r2r")
Path("persistent_storage").mkdir(exist_ok=True)
shutil.copy("config.cpu.yaml", "persistent_storage/config.yaml")
cfg = Path("persistent_storage/config.yaml")
cfg.write_text(cfg.read_text().replace("disable_aaa: false", "disable_aaa: true"))


def _get_app():
    from context_chat_backend.controller import app

    return app


def test_delete_sources_sanitizes_source_ids() -> None:
    called: list[str] = []

    class DummyBackend:
        def delete_document(self, doc_id: str) -> None:
            called.append(doc_id)

    app = _get_app()
    old_backend = getattr(app.state, "rag_backend", None)
    app.state.rag_backend = DummyBackend()
    client = TestClient(app)
    headers = {
        "EX-APP-ID": os.environ["APP_ID"],
        "EX-APP-VERSION": os.environ["APP_VERSION"],
        "OCS-APIRequest": "true",
        "AUTHORIZATION-APP-API": "OjEyMzQ1",
    }

    resp = client.post("/deleteSources", json={"sourceIds": ["files__default: 9069143"]}, headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"message": "All valid sources deleted"}
    assert called == ["files__default:9069143"]
    app.state.rag_backend = old_backend


def test_delete_sources_handles_backend_error() -> None:
    class BadBackend:
        def delete_document(self, doc_id: str) -> None:
            request = httpx.Request("DELETE", f"http://r2r/documents/{doc_id}")
            response = httpx.Response(422, request=request)
            raise httpx.HTTPStatusError("bad id", request=request, response=response)

    app = _get_app()
    old_backend = getattr(app.state, "rag_backend", None)
    app.state.rag_backend = BadBackend()
    client = TestClient(app)
    headers = {
        "EX-APP-ID": os.environ["APP_ID"],
        "EX-APP-VERSION": os.environ["APP_VERSION"],
        "OCS-APIRequest": "true",
        "AUTHORIZATION-APP-API": "OjEyMzQ1",
    }

    resp = client.post("/deleteSources", json={"sourceIds": ["files__default:123"]}, headers=headers)
    assert resp.status_code == 400
    assert resp.json()["failed"] == ["files__default:123"]
    app.state.rag_backend = old_backend
