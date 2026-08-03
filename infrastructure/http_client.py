"""Low-level asynchronous communication with the upstream Jellyfin server."""

from __future__ import annotations

import logging
from time import perf_counter

import httpx
from fastapi import Request


HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}

logger = logging.getLogger(__name__)


class JellyfinHttpClient:
    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=False)

    async def close(self) -> None:
        await self._client.aclose()

    async def forward(self, request: Request) -> httpx.Response:
        raw_path = request.scope.get("raw_path", request.url.path.encode("utf-8")).decode("latin-1")
        query = request.scope.get("query_string", b"").decode("latin-1")
        target_url = f"{self._base_url}{raw_path}"
        if query:
            target_url = f"{target_url}?{query}"

        headers = {
            name: value
            for name, value in request.headers.items()
            if name.lower() not in HOP_BY_HOP_HEADERS | {"host", "content-length"}
        }
        if request.client:
            prior = request.headers.get("x-forwarded-for")
            headers["x-forwarded-for"] = f"{prior}, {request.client.host}" if prior else request.client.host
        headers["x-forwarded-proto"] = request.url.scheme
        headers["x-forwarded-host"] = request.headers.get("host", "")

        started = perf_counter()
        try:
            response = await self._client.request(
                method=request.method,
                url=target_url,
                headers=headers,
                content=await request.body(),
            )
        except httpx.HTTPError:
            logger.exception(
                "upstream_request_failed method=%s path=%s duration_ms=%.2f",
                request.method,
                request.url.path,
                (perf_counter() - started) * 1000,
            )
            raise

        logger.debug(
            "upstream_request_completed method=%s path=%s status=%d duration_ms=%.2f",
            request.method,
            request.url.path,
            response.status_code,
            (perf_counter() - started) * 1000,
        )
        return response
