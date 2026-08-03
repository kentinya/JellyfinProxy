"""Transparent proxy response adapter."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
from fastapi import Request, Response
from starlette.background import BackgroundTask
from starlette.responses import StreamingResponse

from infrastructure.http_client import HOP_BY_HOP_HEADERS, JellyfinHttpClient


def response_headers(upstream: httpx.Response, *, content_changed: bool = False) -> dict[str, str]:
    # httpx exposes decoded ``response.content``. Its original encoding and
    # length therefore never describe the body emitted by this application.
    del content_changed
    # Starlette/Uvicorn supplies Date and Server itself. Keeping the upstream
    # copies would produce duplicate response headers at the outer Nginx proxy.
    excluded = HOP_BY_HOP_HEADERS | {
        "content-length",
        "content-encoding",
        "date",
        "server",
    }
    return {name: value for name, value in upstream.headers.items() if name.lower() not in excluded}


def streaming_response_headers(upstream: httpx.Response) -> dict[str, str]:
    """Preserve representation headers because streamed bytes remain encoded."""

    excluded = HOP_BY_HOP_HEADERS | {"date", "server"}
    return {name: value for name, value in upstream.headers.items() if name.lower() not in excluded}


class ProxyHandler:
    def __init__(self, http_client: JellyfinHttpClient) -> None:
        self._http_client = http_client

    async def handle(self, request: Request) -> Response:
        upstream = await self._http_client.forward_stream(request)

        async def stream_body() -> AsyncIterator[bytes]:
            try:
                async for chunk in upstream.aiter_raw():
                    yield chunk
            finally:
                await upstream.aclose()

        return StreamingResponse(
            content=stream_body(),
            status_code=upstream.status_code,
            headers=streaming_response_headers(upstream),
            background=BackgroundTask(upstream.aclose),
        )
