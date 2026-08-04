"""Wire policies and route categories to HTTP handlers."""

from __future__ import annotations

import logging

from fastapi import Request, Response

from handlers.playback_handler import PlaybackHandler
from handlers.proxy_handler import ProxyHandler
from handlers.video_handler import VideoHandler
from infrastructure.http_client import JellyfinHttpClient
from policies.client_policy import ClientPolicy
from routers.route_config import HandlerType
from routers.router import Router
from services.playback_service import PlaybackService


logger = logging.getLogger(__name__)


class Dispatcher:
    def __init__(
        self,
        router: Router,
        client_policy: ClientPolicy,
        http_client: JellyfinHttpClient,
        playback_service: PlaybackService,
    ) -> None:
        self._router = router
        self._client_policy = client_policy
        self._proxy = ProxyHandler(http_client)
        self._playback = PlaybackHandler(http_client, playback_service)
        self._video = VideoHandler(self._proxy, playback_service.media_source_cache)

    async def dispatch(self, request: Request) -> Response:
        handler_type = self._router.match(request.url.path, request.method)
        if self._client_policy.should_bypass(request.headers, handler_type):
            logger.debug(
                "route_selected handler=proxy reason=client_bypass route=%s",
                handler_type.value,
            )
            return await self._proxy.handle(request)

        logger.debug("route_selected handler=%s", handler_type.value)
        if handler_type is HandlerType.PLAYBACK:
            return await self._playback.handle(request)
        if handler_type is HandlerType.VIDEO:
            return await self._video.handle(request)
        return await self._proxy.handle(request)
