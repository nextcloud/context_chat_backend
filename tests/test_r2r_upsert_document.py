# ruff: noqa: S101
import hashlib
import json
from typing import Any

from context_chat_backend.backends.r2r import R2rBackend


def test_upsert_document_sends_metadata_and_collection_ids(tmp_path):
    backend = R2rBackend.__new__(R2rBackend)
    backend.find_document_by_hash = lambda sha256: None
    backend.find_document_by_title = lambda title: None

    captured = {}

    def fake_request(
        method, path, *, action=None, data=None, files=None, **kwargs
    ):
        captured["method"] = method
        captured["path"] = path
        captured["data"] = data
        captured["files"] = files
        captured["action"] = action
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
    uploaded = json.loads(files["metadata"][1])
    for key, value in metadata.items():
        assert uploaded[key] == value
    assert "sha256" in uploaded
    assert json.loads(files["collection_ids"][1]) == collection_ids
    assert files["ingestion_mode"][1] == "fast"
    assert "file" in files


def test_upsert_document_uses_extension_from_temp_path(tmp_path):
    backend = R2rBackend.__new__(R2rBackend)
    backend.find_document_by_hash = lambda sha256: None
    backend.find_document_by_title = lambda title: None

    captured: dict[str, Any] = {}

    def fake_request(
        method, path, *, action=None, data=None, files=None, **kwargs
    ):
        captured["files"] = files
        captured["action"] = action
        return {"results": {"document_id": "doc1"}}

    backend._request = fake_request  # type: ignore[attr-defined]

    file = tmp_path / "doc.txt"
    file.write_text("hello")

    metadata = {
        "title": "doc.txt",
        "filename": "doc",  # no extension
        "modified": "1",
        "content-length": "5",
    }

    backend.upsert_document(str(file), metadata, ["cid1"])

    files = dict(captured["files"])
    assert files["file"][0] == "doc.txt"


def test_upsert_document_reuses_existing_by_hash(tmp_path):
    backend = R2rBackend.__new__(R2rBackend)

    file = tmp_path / "doc.txt"
    content = "hello"
    file.write_text(content)
    digest = hashlib.sha256(content.encode()).hexdigest()

    def find_by_hash(sha256: str):
        if sha256 == digest:
            return {
                "id": "doc1",
                "metadata": {"sha256": sha256},
                "collection_ids": ["cid1"],
            }
        return None

    backend.find_document_by_hash = find_by_hash
    backend.find_document_by_title = lambda title: None
    backend.get_document = lambda document_id: {
        "id": "doc1",
        "metadata": {"sha256": digest},
        "collection_ids": ["cid1"],
    }
    deleted: list[str] = []

    def delete_document(document_id: str):
        deleted.append(document_id)

    backend.delete_document = delete_document

    calls: list[tuple[str, str, Any, Any, Any]] = []

    def fake_request(
        method, path, *, action=None, data=None, files=None, json=None, **kwargs
    ):
        calls.append((method, path, files, json, action))
        return {}

    backend._request = fake_request  # type: ignore[attr-defined]

    metadata = {
        "title": "doc.txt",
        "filename": "doc.txt",
        "modified": "1",
        "content-length": "5",
    }

    doc_id = backend.upsert_document(str(file), metadata, ["cid1", "cid2"])

    assert doc_id == "doc1"
    assert not deleted
    assert any(path == "collections/cid2/documents/doc1" for _, path, _, _, _ in calls)
    assert any(
        method == "PUT" and path == "documents/doc1/metadata" for method, path, _, _, _ in calls
    )
    assert not any(
        method == "POST" and path == "documents" and files is not None
        for method, path, files, _, _ in calls
    )


def test_find_document_by_hash_returns_none():
    backend = R2rBackend.__new__(R2rBackend)

    captured: dict[str, Any] = {}

    def fake_request(method, path, *, params=None, **kwargs):
        captured["params"] = params
        return {"results": []}

    backend._request = fake_request  # type: ignore[attr-defined]

    assert backend.find_document_by_hash("abc") is None
    assert captured["params"] == {
        "metadata_filter": json.dumps({"sha256": "abc"}),
        "limit": 1,
    }


def test_find_document_by_title_exact_and_mismatch():
    backend = R2rBackend.__new__(R2rBackend)

    calls: list[dict[str, Any]] = []

    def fake_request(method, path, *, params=None, **kwargs):
        calls.append({"params": params})
        return {
            "results": [
                {"id": "doc1", "title": "doc.txt", "metadata": {"title": "doc.txt"}}
            ]
        }

    backend._request = fake_request  # type: ignore[attr-defined]

    doc = backend.find_document_by_title("doc.txt")
    assert doc and doc["id"] == "doc1"
    assert calls[0]["params"] == {
        "metadata_filter": json.dumps({"title": "doc.txt"}),
        "limit": 10,
    }

    def fake_request_mismatch(method, path, *, params=None, **kwargs):
        return {
            "results": [
                {"id": "doc2", "title": "other.txt", "metadata": {"title": "other.txt"}}
            ]
        }

    backend._request = fake_request_mismatch  # type: ignore[attr-defined]
    assert backend.find_document_by_title("doc.txt") is None


def test_upsert_document_ignores_unrelated_document(tmp_path):
    backend = R2rBackend.__new__(R2rBackend)

    file = tmp_path / "doc.txt"
    file.write_text("hello")

    def find_by_hash(sha256: str):
        return {
            "id": "other",
            "metadata": {"sha256": "different"},
            "collection_ids": ["cid1"],
        }

    backend.find_document_by_hash = find_by_hash
    backend.find_document_by_title = lambda title: None
    deleted: list[str] = []

    def delete_document(document_id: str) -> None:
        deleted.append(document_id)

    backend.delete_document = delete_document

    calls: list[tuple[str, str, Any, Any]] = []

    def fake_request(method, path, *, files=None, action=None, **kwargs):
        calls.append((method, path, files, action))
        if method == "POST" and path == "documents":
            return {"results": {"document_id": "new"}}
        return {}

    backend._request = fake_request  # type: ignore[attr-defined]

    metadata = {
        "title": "doc.txt",
        "filename": "doc.txt",
        "modified": "1",
        "content-length": "5",
    }

    doc_id = backend.upsert_document(str(file), metadata, ["cid1"])

    assert doc_id == "new"
    assert deleted == []
    assert any(path == "documents" for _, path, _, _ in calls)


def test_upsert_document_replaces_when_title_matches_hash_diff(tmp_path):
    backend = R2rBackend.__new__(R2rBackend)

    file = tmp_path / "doc.txt"
    content = "new"
    file.write_text(content)

    backend.find_document_by_hash = lambda sha256: None

    existing_stub = {"id": "doc1"}
    existing_full = {
        "id": "doc1",
        "metadata": {"sha256": "old"},
        "collection_ids": ["cid1"],
        "ingestion_status": "success",
    }
    backend.find_document_by_title = lambda title: existing_stub
    backend.get_document = lambda document_id: existing_full

    deleted: list[str] = []
    backend.delete_document = lambda document_id: deleted.append(document_id)

    calls: list[tuple[str, str, Any, Any, Any]] = []

    def fake_request(method, path, *, files=None, json=None, action=None, **kwargs):
        calls.append((method, path, files, json, action))
        if method == "POST" and path == "documents":
            return {"results": {"document_id": "doc2"}}
        return {}

    backend._request = fake_request  # type: ignore[attr-defined]

    metadata = {
        "title": "doc.txt",
        "filename": "doc.txt",
        "modified": "1",
        "content-length": len(content),
    }

    doc_id = backend.upsert_document(str(file), metadata, ["cid1"])

    assert doc_id == "doc2"
    assert deleted == ["doc1"]
    assert any(path == "documents" for _, path, _, _, _ in calls)


def test_upsert_document_skips_pending_ingestion(tmp_path):
    backend = R2rBackend.__new__(R2rBackend)

    file = tmp_path / "doc.txt"
    content = "hello"
    file.write_text(content)

    backend.find_document_by_hash = lambda sha256: None

    existing_stub = {"id": "doc1"}
    existing_full = {
        "id": "doc1",
        "metadata": {"modified": "1", "content-length": "5"},
        "collection_ids": ["cid1"],
        "ingestion_status": "pending",
    }

    backend.find_document_by_title = lambda title: existing_stub
    backend.get_document = lambda document_id: existing_full

    deleted: list[str] = []
    backend.delete_document = lambda document_id: deleted.append(document_id)

    calls: list[tuple[str, str, Any, Any]] = []

    def fake_request(method, path, *, files=None, json=None, action=None, **kwargs):
        calls.append((method, path, files, json))
        return {}

    backend._request = fake_request  # type: ignore[attr-defined]

    metadata = {
        "title": "doc.txt",
        "filename": "doc.txt",
        "modified": "1",
        "content-length": len(content),
    }

    doc_id = backend.upsert_document(str(file), metadata, ["cid1"])

    assert doc_id == "doc1"
    assert deleted == []
    assert not any(method == "POST" and path == "documents" for method, path, _, _ in calls)
