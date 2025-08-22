# ruff: noqa: S101
import json

from context_chat_backend.backends.r2r import R2rBackend


def test_upsert_document_sends_metadata_and_collection_ids(tmp_path):
    backend = R2rBackend.__new__(R2rBackend)
    backend.find_document_by_title = lambda title: None

    captured = {}

    def fake_request(method, path, data=None, files=None):
        captured["method"] = method
        captured["path"] = path
        captured["data"] = data
        captured["files"] = files
        return {"results": {"document_id": "doc1"}}

    backend._request = fake_request  # type: ignore[attr-defined]

    file = tmp_path / "doc.txt"
    file.write_text("hello")

    metadata = {
        "title": "doc.txt",
        "filename": "doc.txt",
        "modified": "1",
        "content-length": "5",
    }
    collection_ids = ["cid1"]

    doc_id = backend.upsert_document(str(file), metadata, collection_ids)

    assert doc_id == "doc1"
    assert json.loads(captured["data"]["metadata"]) == metadata
    assert json.loads(captured["data"]["collection_ids"]) == collection_ids
    assert captured["data"]["ingestion_mode"] == "fast"
    assert "file" in captured["files"]
