"""Extensible interception point for all Jellyfin video routes."""

from __future__ import annotations

from fastapi import Request, Response
from fastapi.responses import RedirectResponse

from handlers.proxy_handler import ProxyHandler
from services.media_source_cache import MediaSourceCache


class VideoHandler:
    """Redirect cached remote media sources and proxy all other video requests."""

    def __init__(
        self,
        proxy_handler: ProxyHandler,
        media_source_cache: MediaSourceCache,
    ) -> None:
        self._proxy_handler = proxy_handler
        self._media_source_cache = media_source_cache

    async def handle(self, request: Request) -> Response:
        media_source_id = request.query_params.get("MediaSourceId")
        if media_source_id:
            path = self._media_source_cache.get(media_source_id)
            if path is not None:
                return RedirectResponse(path, status_code=302)
        return await self._proxy_handler.handle(request)
