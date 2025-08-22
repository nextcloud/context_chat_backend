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
    files = dict(captured["files"])
    assert json.loads(files["metadata"][1]) == metadata
    assert json.loads(files["collection_ids"][1]) == collection_ids
    assert files["ingestion_mode"][1] == "fast"
    assert "file" in files
