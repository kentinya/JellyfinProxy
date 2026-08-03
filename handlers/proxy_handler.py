"""Transparent proxy response adapter."""

from __future__ import annotations

import httpx
from fastapi import Request, Response

from infrastructure.http_client import HOP_BY_HOP_HEADERS, JellyfinHttpClient


def response_headers(upstream: httpx.Response, *, content_changed: bool = False) -> dict[str, str]:
    # httpx exposes decoded ``response.content``. Its original encoding and
    # length therefore never describe the body emitted by this application.
    del content_changed
    excluded = HOP_BY_HOP_HEADERS | {"content-length", "content-encoding"}
    return {name: value for name, value in upstream.headers.items() if name.lower() not in excluded}


class ProxyHandler:
    def __init__(self, http_client: JellyfinHttpClient) -> None:
        self._http_client = http_client

    async def handle(self, request: Request) -> Response:
        upstream = await self._http_client.forward(request)
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers=response_headers(upstream),
        )
