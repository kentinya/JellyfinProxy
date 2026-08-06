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
from services.playback_info_cache import PlaybackInfoCache


logger = logging.getLogger(__name__)
CLIENT_HEADER_LIMIT = 256


def _safe_client_header(value: str | None) -> str:
    """Make a client identity header safe and compact enough for one log line."""

    cleaned = "".join(" " if ord(character) < 32 or ord(character) == 127 else character for character in (value or ""))
    return cleaned[:CLIENT_HEADER_LIMIT]


class Dispatcher:
    def __init__(
        self,
        router: Router,
        client_policy: ClientPolicy,
        http_client: JellyfinHttpClient,
        playback_service: PlaybackService,
        playback_info_cache: PlaybackInfoCache | None = None,
    ) -> None:
        self._router = router
        self._client_policy = client_policy
        self._proxy = ProxyHandler(http_client)
        self._playback = PlaybackHandler(http_client, playback_service, playback_info_cache)
        self._video = VideoHandler(self._proxy, playback_service.media_source_cache)

    async def dispatch(self, request: Request) -> Response:
        handler_type = self._router.match(request.url.path, request.method)
        bypass = self._client_policy.should_bypass(request.headers, handler_type)
        cache_bypass = (
            handler_type is HandlerType.PLAYBACK
            and self._client_policy.should_bypass_playback_cache(request.headers)
        )
        if handler_type in (HandlerType.PLAYBACK, HandlerType.VIDEO):
            logger.info(
                "client_identified route=%s action=%s cache=%s emby_client=%r device_name=%r "
                "device_id=%r user_agent=%r",
                handler_type.value,
                "bypass" if bypass else "modify",
                "bypass" if cache_bypass else "enabled",
                _safe_client_header(request.headers.get("x-emby-client")),
                _safe_client_header(request.headers.get("x-emby-device-name")),
                _safe_client_header(request.headers.get("x-emby-device-id")),
                _safe_client_header(request.headers.get("user-agent")),
            )

        if bypass and handler_type is not HandlerType.PLAYBACK:
            logger.debug(
                "route_selected handler=proxy reason=client_bypass route=%s",
                handler_type.value,
            )
            return await self._proxy.handle(request)

        logger.debug("route_selected handler=%s", handler_type.value)
        if handler_type is HandlerType.PLAYBACK:
            return await self._playback.handle(
                request,
                modify=not bypass,
                use_cache=not cache_bypass,
            )
        if handler_type is HandlerType.VIDEO:
            return await self._video.handle(request)
        return await self._proxy.handle(request)
