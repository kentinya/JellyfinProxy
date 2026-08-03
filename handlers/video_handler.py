"""Extensible interception point for all Jellyfin video routes."""

from __future__ import annotations

from fastapi import Request, Response

from handlers.proxy_handler import ProxyHandler


class VideoHandler:
    """Currently delegates transparently; future range/URL handling belongs here."""

    def __init__(self, proxy_handler: ProxyHandler) -> None:
        self._proxy_handler = proxy_handler

    async def handle(self, request: Request) -> Response:
        return await self._proxy_handler.handle(request)
