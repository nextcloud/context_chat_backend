import asyncio
import logging
from collections.abc import Iterable
from io import BytesIO

import httpx

from .ocs_utils import sign_request

logger = logging.getLogger("ccb.startup_test")


async def _document_lifecycle(base_url: str, client: httpx.AsyncClient) -> None:
    """End-to-end test: upload -> search -> delete -> verify deletion."""
    user_id = "startup-test-user"
    filename = "startup-test.txt"
    content = b"hello world"
    headers = {
        "userIds": user_id,
        "title": filename,
        "type": "text/plain",
        "modified": "1",
        "provider": "startup-test",
    }

    files = {"sources": (filename, BytesIO(content), "text/plain", headers)}
    req_headers: dict[str, str] = {}
    sign_request(req_headers)
    try:
        resp = await client.put(f"{base_url}/loadSources", files=files, headers=req_headers)
    except Exception as e:  # pragma: no cover - network issues
        logger.error("PUT /loadSources failed", exc_info=e)
        return
    if resp.status_code != 200:
        logger.error("PUT /loadSources failed", extra={"status": resp.status_code, "body": resp.text})
        return
    loaded = resp.json().get("loaded_sources", [])
    if not loaded:
        logger.error("PUT /loadSources did not return source ids", extra={"response": resp.text})
        return
    source_id = loaded[0]
    logger.info("Loaded test document", extra={"source_id": source_id})

    query_payload = {"userId": user_id, "query": "hello", "useContext": True}
    resp = await client.post(f"{base_url}/docSearch", json=query_payload, headers=req_headers)
    if resp.status_code == 200 and resp.json():
        logger.info("docSearch returned results", extra={"hits": len(resp.json())})
    else:
        logger.error(
            "docSearch failed to return results",
            extra={"status": resp.status_code, "body": resp.text},
        )

    resp = await client.post(
        f"{base_url}/deleteSources", json={"sourceIds": [source_id]}, headers=req_headers
    )
    if resp.status_code == 200:
        logger.info("deleteSources succeeded")
    else:
        logger.error(
            "deleteSources failed", extra={"status": resp.status_code, "body": resp.text}
        )

    resp = await client.post(f"{base_url}/docSearch", json=query_payload, headers=req_headers)
    if resp.status_code == 200 and not resp.json():
        logger.info("Deletion verified: no results returned")
    else:
        logger.error(
            "Deletion verification failed",
            extra={"status": resp.status_code, "body": resp.text},
        )


async def _check_route(client: httpx.AsyncClient, method: str, url: str) -> None:
    headers: dict[str, str] = {}
    sign_request(headers)
    try:
        resp = await client.request(method, url, headers=headers)
        logger.info(
            "Checked route",
            extra={"method": method, "url": url, "status": resp.status_code},
        )
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
    async with httpx.AsyncClient(timeout=10.0) as client:
        enabled = False
        try:
            resp = await client.get(f"{base_url}/enabled")
            if resp.status_code == 200:
                body = resp.text.strip().lower()
                enabled = body == "true" or body == "1"
        except Exception as e:  # pragma: no cover - network issues
            logger.error("GET /enabled failed", exc_info=e)

        if enabled:
            try:
                await _document_lifecycle(base_url, client)
            except Exception as e:  # pragma: no cover - network issues
                logger.error("Document lifecycle test failed", exc_info=e)
        else:
            logger.info("Context Chat disabled; skipping document lifecycle test")

        await _per_route_checks(base_url, client)


if __name__ == "__main__":
    asyncio.run(run_startup_tests("http://localhost:9000"))
