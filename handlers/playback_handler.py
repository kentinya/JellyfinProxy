"""Handler for upstream PlaybackInfo responses."""

from __future__ import annotations

import json
import logging
from hashlib import sha256
import re

from fastapi import Request, Response

from handlers.proxy_handler import response_headers
from infrastructure.http_client import JellyfinHttpClient
from services.playback_service import PlaybackService
from services.playback_info_cache import PlaybackInfoCache


logger = logging.getLogger(__name__)
PLAYBACK_PATH = re.compile(r"^/(?:emby/)?Items/([^/]+)/PlaybackInfo/?$", re.IGNORECASE)


class PlaybackHandler:
    def __init__(
        self,
        http_client: JellyfinHttpClient,
        service: PlaybackService,
        cache: PlaybackInfoCache | None = None,
    ) -> None:
        self._http_client = http_client
        self._service = service
        self._cache = cache

    async def _cache_key(self, request: Request) -> str:
        """Share one PlaybackInfo entry per item across every client and device."""

        match = PLAYBACK_PATH.match(request.url.path)
        item_id = match.group(1) if match else request.url.path
        compact_id = item_id.replace("-", "")
        normalized = compact_id.casefold() if len(compact_id) == 32 else item_id.casefold()
        return sha256(normalized.encode("utf-8")).hexdigest()

    async def handle(
        self,
        request: Request,
        *,
        modify: bool = True,
        use_cache: bool = True,
    ) -> Response:
        active_cache = self._cache if use_cache else None
        cache_key = await self._cache_key(request) if active_cache is not None else None
        cached = active_cache.get(cache_key) if active_cache is not None and cache_key else None
        if cached is not None:
            logger.info("playback_info_cache status=hit")
            if modify:
                document = json.loads(cached.body)
                body = json.dumps(
                    await self._service.modify(document),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            else:
                self._service.remember_media_sources(json.loads(cached.body))
                body = cached.body
            return Response(
                content=body,
                status_code=200,
                headers={"x-jellyfinproxy-cache": "HIT"},
                media_type="application/json",
            )

        upstream = await self._http_client.forward(request)
        if not upstream.is_success:
            return Response(
                content=upstream.content,
                status_code=upstream.status_code,
                headers=response_headers(upstream),
            )
        try:
            document = upstream.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            return Response(
                content=upstream.content,
                status_code=upstream.status_code,
                headers=response_headers(upstream),
            )

        if active_cache is not None and cache_key is not None:
            active_cache.remember(cache_key, upstream.content)
            logger.info("playback_info_cache status=miss action=stored")
        if modify:
            modified = await self._service.modify(document)
            body = json.dumps(modified, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        else:
            self._service.remember_media_sources(document)
            body = upstream.content
        return Response(
            content=body,
            status_code=upstream.status_code,
            headers={
                **response_headers(upstream, content_changed=modify),
                "x-jellyfinproxy-cache": "MISS",
            },
            media_type="application/json",
        )
