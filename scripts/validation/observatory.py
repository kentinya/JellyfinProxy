"""Transparent observation entry point for real Jellyfin validation.

Strict contract for this module:

* every request received here is forwarded to the real Jellyfin 12.3 server;
* nothing is cached, retried, synthesised or rewritten in the response;
* redirects are never followed;
* media bodies are streamed, never buffered;
* only a limited, redacted JSON copy plus byte digests are persisted.

The tool (not the proxy) owns this process, and it is bound to loopback only.
"""

from __future__ import annotations

import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator
from uuid import uuid4

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from scripts.validation.common import (
    canonical_json,
    redact,
    redact_text,
    sha256_bytes,
)

HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
    "accept-encoding",
}

#: Single, declared representation adaptation: the observatory always requests an
#: identity representation (RFC 9110 allows any recipient to do so) so that the
#: stored JSON copy and byte digests describe the same bytes the client receives.
#: The response's own Content-Encoding header is forwarded untouched.
REPRESENTATION_ADAPTATION = "accept-encoding: identity requested from the real upstream"
LOGGED_RESPONSE_HEADERS = {
    "content-type",
    "content-length",
    "content-range",
    "accept-ranges",
    "location",
    "x-request-id",
    "x-jellyfinproxy-cache",
    "x-jellyfinproxy-version",
}
LOGGED_REQUEST_HEADERS = (
    "x-request-id",
    "user-agent",
    "x-emby-client",
    "x-emby-device-name",
    "x-emby-device-id",
    "content-type",
    "range",
)

TARGET = os.environ.get("S1_OBS_TARGET", "").rstrip("/")
LOG_PATH = Path(os.environ.get("S1_OBS_LOG", "observatory.jsonl"))
MAX_JSON_BYTES = int(os.environ.get("S1_OBS_MAX_JSON", "65536"))
CONTROL_PATH = "/__s1/control"


class Recorder:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._sequence = 0
        self._group = "unset"
        self._handle = path.open("a", encoding="utf-8")

    def set_group(self, group: str) -> None:
        self._group = group

    @property
    def group(self) -> str:
        return self._group

    def write(self, record: dict[str, Any]) -> None:
        self._sequence += 1
        record["seq"] = self._sequence
        record["group"] = self._group
        self._handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        self._handle.flush()

    def close(self) -> None:
        self._handle.close()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    if not TARGET:
        raise RuntimeError("S1_OBS_TARGET is required")
    app.state.recorder = Recorder(LOG_PATH)
    app.state.client = httpx.AsyncClient(timeout=None, follow_redirects=False)
    try:
        yield
    finally:
        await app.state.client.aclose()
        app.state.recorder.close()


app = FastAPI(title="S1-observatory", lifespan=lifespan)


@app.post(CONTROL_PATH)
async def control(request: Request) -> JSONResponse:
    payload = await request.json()
    group = str(payload.get("group", "unset"))
    request.app.state.recorder.set_group(group)
    return JSONResponse({"group": group})


@app.get(CONTROL_PATH)
async def control_state(request: Request) -> JSONResponse:
    return JSONResponse({"group": request.app.state.recorder.group, "target": TARGET})


@app.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
)
async def observe(request: Request, path: str) -> Response:
    del path
    client: httpx.AsyncClient = request.app.state.client
    recorder: Recorder = request.app.state.recorder
    request_id = uuid4().hex
    raw_path = request.scope.get("raw_path", request.url.path.encode("utf-8")).decode("latin-1")
    query = request.scope.get("query_string", b"").decode("latin-1")
    body = await request.body()
    headers = {
        name: value
        for name, value in request.headers.items()
        if name.lower() not in HOP_BY_HOP
    }
    headers["accept-encoding"] = "identity"
    target_url = f"{TARGET}{raw_path}" + (f"?{query}" if query else "")
    record: dict[str, Any] = {
        "id": request_id,
        "ts": round(time.time(), 3),
        "method": request.method,
        "path": raw_path,
        "query": redact_text(query) if query else "",
        "request_headers": {
            name: redact_text(request.headers.get(name, "")) for name in LOGGED_REQUEST_HEADERS
        },
        "request_body_sha256": sha256_bytes(body) if body else None,
        "request_body_bytes": len(body),
        "upstream_url_digest_prefix": sha256_bytes(target_url.encode("utf-8"))[:12],
        "representation_adaptation": REPRESENTATION_ADAPTATION,
    }
    upstream_request = client.build_request(
        method=request.method,
        url=target_url,
        headers=headers,
        content=body,
    )
    started = time.monotonic()
    try:
        upstream = await client.send(upstream_request, stream=True)
    except httpx.HTTPError as exc:
        record.update(
            {
                "error": type(exc).__name__,
                "status": None,
                "completed_ms": round((time.monotonic() - started) * 1000, 3),
                "client_closed": False,
            }
        )
        recorder.write(record)
        return Response(status_code=502, content=b'{"error":"upstream_unreachable"}', media_type="application/json")

    response_headers = {
        name: value
        for name, value in upstream.headers.items()
        if name.lower() not in HOP_BY_HOP | {"date", "server"}
    }
    record["status"] = upstream.status_code
    record["response_headers"] = {
        name: redact_text(value)
        for name, value in upstream.headers.items()
        if name.lower() in LOGGED_RESPONSE_HEADERS
    }
    content_type = upstream.headers.get("content-type", "")
    declared_length = upstream.headers.get("content-length")
    is_small_json = content_type.startswith("application/json") and (
        declared_length is None or int(declared_length) <= MAX_JSON_BYTES
    )

    if is_small_json or request.method == "HEAD":
        # Accumulate the *raw* representation so Content-Encoding stays truthful.
        buffer = bytearray()
        try:
            async for chunk in upstream.aiter_raw():
                buffer.extend(chunk)
        finally:
            await upstream.aclose()
        payload = bytes(buffer)
        record["response_body_sha256"] = sha256_bytes(payload)
        record["response_body_bytes"] = len(payload)
        record["first_chunk_ms"] = round((time.monotonic() - started) * 1000, 3)
        record["completed_ms"] = record["first_chunk_ms"]
        record["client_closed"] = False
        if is_small_json and payload:
            try:
                parsed = json.loads(payload)
            except (ValueError, UnicodeDecodeError):
                record["json_invalid"] = True
                record["response_prefix_sha256"] = sha256_bytes(payload)[:16]
            else:
                record["json"] = redact(parsed)
                record["json_sha256"] = sha256_bytes(canonical_json(parsed))
        recorder.write(record)
        return Response(
            content=payload,
            status_code=upstream.status_code,
            headers=response_headers,
        )

    async def stream() -> AsyncIterator[bytes]:
        digest_state = bytearray()
        sent = 0
        first_chunk_ms: float | None = None
        try:
            async for chunk in upstream.aiter_raw():
                if first_chunk_ms is None:
                    first_chunk_ms = round((time.monotonic() - started) * 1000, 3)
                digest_state.extend(chunk)
                sent += len(chunk)
                yield chunk
            record["client_closed"] = False
        except (GeneratorExit, BaseException) as exc:  # noqa: BLE001 - cancellation is expected
            record["client_closed"] = True
            record["cancel_exception"] = type(exc).__name__
            raise
        finally:
            completed = round((time.monotonic() - started) * 1000, 3)
            record["response_body_sha256"] = sha256_bytes(bytes(digest_state))
            record["response_body_bytes"] = sent
            record["first_chunk_ms"] = first_chunk_ms
            record["completed_ms"] = completed
            record["streamed"] = True
            await upstream.aclose()
            recorder.write(record)

    return StreamingResponse(
        stream(),
        status_code=upstream.status_code,
        headers=response_headers,
    )
