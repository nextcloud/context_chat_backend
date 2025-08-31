"""Startup lifecycle tests.

This module performs a small end-to-end document lifecycle against the
configured R2R backend when the app starts.  It now uploads a real
document from the repository and logs every HTTP request as a fully
reproducible ``curl`` command with headers and payload, making it easier
to diagnose issues from container logs.
"""

import asyncio
import json
import logging
from collections.abc import Iterable
from io import BytesIO
from pathlib import Path

import httpx

from .ocs_utils import sign_request

logger = logging.getLogger("ccb.startup_test")


async def _call(
    client: httpx.AsyncClient, method: str, url: str, **kwargs
) -> httpx.Response:
    """Send request and log a curl-equivalent command and response."""

    headers: dict[str, str] = kwargs.get("headers", {})
    parts = ["curl -i", f"-X {method.upper()}"]
    for key, value in headers.items():
        parts.append(f"-H '{key}: {value}'")

    body: str | None = None
    if kwargs.get("json") is not None:
        body = json.dumps(kwargs["json"], separators=(",", ":"))
        parts.append("--data-raw @-")
    elif kwargs.get("data") is not None:
        raw = kwargs["data"]
        body = raw if isinstance(raw, str) else raw.decode()
        parts.append("--data-raw @-")
    elif kwargs.get("files") is not None:
        # log file uploads and their content
        file_logs = []
        for field, (fname, fileobj, ctype, file_headers) in kwargs["files"].items():
            parts.append(f"-F '{field}=@{fname};type={ctype}'")
            for hk, hv in file_headers.items():
                parts.append(f"-H '{hk}: {hv}'")
            if hasattr(fileobj, "getvalue"):
                file_content = fileobj.getvalue().decode("utf-8", "ignore")
                file_logs.append(f"---{field} content---\n{file_content}\n---end {field}---")
        if file_logs:
            body = "\n".join(file_logs)

    curl_cmd = " ".join(parts) + f" {url}"
    logger.info("CMD %s", curl_cmd)
    if body:
        logger.info("BODY\n%s", body)

    resp = await client.request(method, url, **kwargs)
    logger.info("RESULT %s %s", resp.status_code, resp.text)
    return resp


async def _verify_deletion_with_retry(
    client: httpx.AsyncClient,
    base_url: str,
    query_payload: dict,
    headers: dict[str, str],
    deleted_source_id: str | None = None,
    deleted_title: str | None = None,
    retries: int = 3,
    initial_delay: float = 0.1,
) -> bool:
    """Ensure a document no longer appears in ``/docSearch`` results.

    The R2R backend may contain pre-existing data, so ``/docSearch`` might
    still return hits even after we delete the startup test document.
    Instead of requiring an empty result set, verify that the deleted
    document identified by ``deleted_source_id`` or ``deleted_title`` is not
    present.  Retries the search with exponential backoff before logging an
    error.
    """

    delay = initial_delay
    resp: httpx.Response | None = None
    for attempt in range(retries):
        resp = await _call(
            client,
            "POST",
            f"{base_url}/docSearch",
            json=query_payload,
            headers=headers,
        )
        if resp.status_code == 200:
            results = resp.json()
            if not results:
                logger.info("Deletion verified: no results returned")
                return True
            missing = True
            for r in results:
                sid = r.get("sourceId")
                title = r.get("title")
                if deleted_source_id and sid == deleted_source_id:
                    missing = False
                    break
                if deleted_title and title == deleted_title:
                    missing = False
                    break
            if missing:
                logger.info("Deletion verified: document absent in results")
                return True
        if attempt < retries - 1:
            await asyncio.sleep(delay)
            delay *= 2
    if resp is not None:
        logger.error(
            "Deletion verification failed",
            extra={"status": resp.status_code, "body": resp.text},
        )
    return False


async def _document_lifecycle(base_url: str, client: httpx.AsyncClient) -> None:
    """End-to-end test: upload -> list -> update -> search -> delete."""
    user_id = "startup-test-user"
    doc_path = Path(__file__).resolve().parent.parent / "R2RAPIEndpointsSummary.txt"
    try:
        content = doc_path.read_bytes()
        filename = doc_path.name
    except Exception:  # pragma: no cover - file missing
        filename = "startup-test.txt"
        content = b"hello world"

    source_id = "startup-test__default:1"
    headers = {
        "userIds": user_id,
        "title": filename,
        "type": "text/plain",
        "modified": "1",
        "provider": source_id.split(":")[0],
    }

    files = {"sources": (source_id, BytesIO(content), "text/plain", headers)}
    req_headers: dict[str, str] = {}
    sign_request(req_headers)

    resp = await _call(
        client, "PUT", f"{base_url}/loadSources", files=files, headers=req_headers
    )
    if resp.status_code != 200:
        return
    loaded = resp.json().get("loaded_sources", [])
    if not loaded:
        logger.error("PUT /loadSources did not return source ids", extra={"response": resp.text})
        return
    source_id = loaded[0]
    logger.info("Loaded test document", extra={"source_id": source_id})

    # list
    await _call(client, "POST", f"{base_url}/countIndexedDocuments", headers=req_headers)

    # update
    update_payload = {
        "op": "allow",
        "userIds": ["startup-test-user2"],
        "sourceId": source_id,
    }
    await _call(
        client, "POST", f"{base_url}/updateAccess", json=update_payload, headers=req_headers
    )

    # search
    query_payload = {"userId": user_id, "query": "Retrieval", "useContext": True}
    resp = await _call(
        client, "POST", f"{base_url}/docSearch", json=query_payload, headers=req_headers
    )
    if resp.status_code == 200 and resp.json():
        logger.info("docSearch returned results", extra={"hits": len(resp.json())})

    # delete
    await _call(
        client,
        "POST",
        f"{base_url}/deleteSources",
        json={"sourceIds": [source_id]},
        headers=req_headers,
    )

    # verify deletion
    await _call(client, "POST", f"{base_url}/countIndexedDocuments", headers=req_headers)
    await _verify_deletion_with_retry(
        client,
        base_url,
        query_payload,
        req_headers,
        deleted_source_id=source_id,
        deleted_title=filename,
    )


async def _check_route(client: httpx.AsyncClient, method: str, url: str) -> None:
    headers: dict[str, str] = {}
    sign_request(headers)
    try:
        await _call(client, method, url, headers=headers)
    except Exception as e:  # pragma: no cover - network issues
        logger.error(
            "Route check failed",
            extra={"method": method, "url": url, "error": str(e)},
        )


async def _per_route_checks(base_url: str, client: httpx.AsyncClient) -> None:
    routes: Iterable[tuple[str, str]] = [
        ("GET", f"{base_url}/"),
        ("GET", f"{base_url}/enabled"),
        ("POST", f"{base_url}/countIndexedDocuments"),
    ]
    for method, url in routes:
        await _check_route(client, method, url)


async def run_startup_tests(base_url: str) -> None:
    async with httpx.AsyncClient(timeout=60.0) as client:
        headers: dict[str, str] = {}
        sign_request(headers)
        enabled = False
        try:
            resp = await client.get(f"{base_url}/enabled", headers=headers)
            if resp.status_code == 200:
                enabled = resp.json().get("enabled", False)
        except Exception as e:  # pragma: no cover - network issues
            logger.error("GET /enabled failed", exc_info=e)

        if not enabled:
            try:
                resp = await client.put(
                    f"{base_url}/enabled", params={"enabled": 1}, headers=headers
                )
                enabled = resp.status_code == 200
                if enabled:
                    logger.info("App enabled via PUT /enabled")
            except Exception as e:  # pragma: no cover - network issues
                logger.error("PUT /enabled failed", exc_info=e)

        if enabled:
            try:
                await _document_lifecycle(base_url, client)
            except Exception as e:  # pragma: no cover - network issues
                logger.error("Document lifecycle test failed", exc_info=e)
        else:
            logger.error(
                "Context Chat disabled; skipping document lifecycle test"
            )

        await _per_route_checks(base_url, client)


if __name__ == "__main__":
    asyncio.run(run_startup_tests("http://localhost:9000"))
