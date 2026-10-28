"""Extensible interception point for all Jellyfin video routes."""

from __future__ import annotations

import logging

from fastapi import Request, Response
from fastapi.responses import RedirectResponse

from handlers.proxy_handler import ProxyHandler
from services.media_source_cache import MediaSourceCache


logger = logging.getLogger(__name__)


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
        if request.method.upper() == "HEAD":
            response = await self._proxy_handler.handle(request)
            self._log_result(
                request,
                handling="proxy",
                mapping="not_queried",
                status=response.status_code,
            )
            return response

        media_source_id = (
            request.query_params.get("MediaSourceId")
            or request.query_params.get("mediaSourceId")
        )
        if not media_source_id:
            path_parts = request.url.path.strip("/").split("/")
            if len(path_parts) >= 2 and path_parts[0].casefold() == "videos":
                media_source_id = path_parts[1]
        if media_source_id:
            path = self._media_source_cache.get(media_source_id)
            if path is not None:
                response = RedirectResponse(path, status_code=302)
                self._log_result(
                    request,
                    handling="redirect",
                    mapping="hit",
                    status=response.status_code,
                )
                return response

        response = await self._proxy_handler.handle(request)
        self._log_result(
            request,
            handling="proxy",
            mapping="miss" if media_source_id else "not_queried",
            status=response.status_code,
        )
        return response

    @staticmethod
    def _log_result(request: Request, *, handling: str, mapping: str, status: int) -> None:
        # Only the path is logged; query strings, cookies and redirect URLs can
        # carry credentials or signed media addresses.
        logger.info(
            "video_request_result method=%s path=%s handling=%s mapping=%s status=%d",
            request.method,
            request.url.path,
            handling,
            mapping,
            status,
        )
