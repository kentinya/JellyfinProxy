"""HTTP client used by the baseline scenarios.

It behaves like a test client, never like a product component: it sends exactly
the headers/body the scenario specifies, never follows redirects silently, and
can abandon a streaming response to make cancellation observable.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Mapping
from uuid import uuid4

import httpx

from scripts.validation.common import sha256_bytes

CLIENT_HEADER = "x-emby-client"
DEVICE_NAME_HEADER = "x-emby-device-name"
DEVICE_ID_HEADER = "x-emby-device-id"


@dataclass
class Response:
    status: int
    headers: dict[str, str]
    body: bytes
    elapsed_ms: float
    url: str
    request_id: str
    history: list[tuple[int, str]] = field(default_factory=list)

    @property
    def body_sha256(self) -> str:
        return sha256_bytes(self.body)

    def header(self, name: str, default: str | None = None) -> str | None:
        return self.headers.get(name.casefold(), default)

    def json_body(self) -> Any:
        import json

        return json.loads(self.body)

    def summary(self) -> dict[str, Any]:
        kept = {
            key: self.headers[key]
            for key in (
                "content-type",
                "content-length",
                "content-range",
                "accept-ranges",
                "location",
                "x-jellyfinproxy-cache",
                "x-jellyfinproxy-version",
                "x-request-id",
            )
            if key in self.headers
        }
        return {
            "status": self.status,
            "headers": kept,
            "body_bytes": len(self.body),
            "body_sha256": self.body_sha256,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "request_id": self.request_id,
        }


def identity_headers(
    client: str,
    device: str,
    *,
    device_id: str | None = None,
    form: str = "x-emby-client",
    token: str | None = None,
) -> dict[str, str]:
    """Build client-identity headers in one of the three supported positions."""

    headers: dict[str, str] = {}
    if form == "x-emby-client":
        headers[CLIENT_HEADER] = client
        headers[DEVICE_NAME_HEADER] = device
    elif form == "x-emby-device-name":
        headers[DEVICE_NAME_HEADER] = client
        headers["user-agent"] = f"{device}/1.0"
    elif form == "user-agent":
        headers["user-agent"] = f"{client}/{device}"
    else:
        raise ValueError(f"unknown identity form {form!r}")
    if device_id:
        headers[DEVICE_ID_HEADER] = device_id
    if token:
        headers["authorization"] = (
            f'MediaBrowser Client="{client}", Device="{device}", '
            f'DeviceId="{device_id or device}", Version="1.0", Token={token}'
        )
    return headers


class TestClient:
    def __init__(self, base_url: str, *, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout, follow_redirects=False)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "TestClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        json_body: Any | None = None,
        request_id: str | None = None,
        follow: bool = False,
    ) -> Response:
        sent_headers = dict(headers or {})
        rid = request_id if request_id is not None else uuid4().hex
        if request_id is not None:
            sent_headers["x-request-id"] = request_id
        content = body
        if json_body is not None:
            import json

            content = json.dumps(json_body).encode("utf-8")
            sent_headers.setdefault("content-type", "application/json")
        started = time.monotonic()
        response = self._client.request(
            method,
            f"{self.base_url}{path}",
            headers=sent_headers,
            content=content,
            follow_redirects=follow,
        )
        elapsed = (time.monotonic() - started) * 1000
        return Response(
            status=response.status_code,
            headers={key.casefold(): value for key, value in response.headers.items()},
            body=response.content,
            elapsed_ms=elapsed,
            url=str(response.request.url),
            request_id=rid,
            history=[(item.status_code, str(item.headers.get("location", ""))) for item in response.history],
        )

    def get(self, path: str, **kwargs: Any) -> Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Response:
        return self.request("POST", path, **kwargs)

    def stream_partial(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        max_bytes: int = 65536,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Read only part of a streaming body, then abandon the connection."""

        started = time.monotonic()
        received = 0
        first_chunk_ms: float | None = None
        chunks = 0
        status = 0
        response_headers: dict[str, str] = {}
        try:
            with self._client.stream(
                "GET", f"{self.base_url}{path}", headers=dict(headers or {}), timeout=timeout
            ) as response:
                status = response.status_code
                response_headers = {key.casefold(): value for key, value in response.headers.items()}
                for chunk in response.iter_raw():
                    if first_chunk_ms is None:
                        first_chunk_ms = (time.monotonic() - started) * 1000
                    received += len(chunk)
                    chunks += 1
                    if received >= max_bytes:
                        break
        except httpx.HTTPError as exc:
            return {
                "status": status,
                "headers": response_headers,
                "bytes_read": received,
                "chunks": chunks,
                "first_chunk_ms": first_chunk_ms,
                "aborted": True,
                "error": type(exc).__name__,
                "elapsed_ms": (time.monotonic() - started) * 1000,
            }
        return {
            "status": status,
            "headers": response_headers,
            "bytes_read": received,
            "chunks": chunks,
            "first_chunk_ms": first_chunk_ms,
            "aborted": True,
            "elapsed_ms": (time.monotonic() - started) * 1000,
        }


def read_full(url: str, *, headers: Mapping[str, str] | None = None, max_bytes: int = 1 << 20) -> dict[str, Any]:
    """Follow a redirect target and read a bounded amount of real media bytes."""

    started = time.monotonic()
    with httpx.Client(timeout=60, follow_redirects=False) as client:
        with client.stream("GET", url, headers=dict(headers or {})) as response:
            digest = bytearray()
            received = 0
            for chunk in response.iter_raw():
                digest.extend(chunk)
                received += len(chunk)
                if received >= max_bytes:
                    break
            return {
                "status": response.status_code,
                "headers": {
                    key.casefold(): value
                    for key, value in response.headers.items()
                    if key.casefold()
                    in {"content-type", "content-length", "content-range", "accept-ranges", "location"}
                },
                "bytes_read": received,
                "sha256": sha256_bytes(bytes(digest)),
                "elapsed_ms": (time.monotonic() - started) * 1000,
            }
