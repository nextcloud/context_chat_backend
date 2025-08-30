# ruff: noqa: S101
from context_chat_backend.utils import sanitize_source_ids


def test_sanitize_source_ids() -> None:
    raw = [
        " files__default: 9013252 ",
        "invalid",
        "files__default:9013266",
        "8d72f8f3-de91-5e3e-8d5d-b32fa2d900dc",
    ]
    assert sanitize_source_ids(raw) == [
        "files__default:9013252",
        "files__default:9013266",
        "8d72f8f3-de91-5e3e-8d5d-b32fa2d900dc",
    ]
