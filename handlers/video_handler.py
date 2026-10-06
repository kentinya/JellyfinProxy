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
        media_source_id = (
            request.query_params.get("MediaSourceId")
            or request.query_params.get("mediaSourceId")
        )
        if not media_source_id:
            path_parts = request.url.path.strip("/").split("/")
            if len(path_parts) >= 2 and path_parts[0].casefold() == "videos":
                media_source_id = path_parts[1]
            else:
                danmu_parts = path_parts[1:] if path_parts and path_parts[0].casefold() == "emby" else path_parts
                if (
                    len(danmu_parts) == 4
                    and danmu_parts[0].casefold() == "api"
                    and danmu_parts[1].casefold() == "danmu"
                    and danmu_parts[3].casefold() == "raw"
                ):
                    media_source_id = danmu_parts[2]
        if media_source_id:
            path = self._media_source_cache.get(media_source_id)
            if path is not None:
                return RedirectResponse(path, status_code=302)
        return await self._proxy_handler.handle(request)
