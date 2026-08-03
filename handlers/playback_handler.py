"""Handler for upstream PlaybackInfo responses."""

from __future__ import annotations

import json

from fastapi import Request, Response

from handlers.proxy_handler import response_headers
from infrastructure.http_client import JellyfinHttpClient
from services.playback_service import PlaybackService


class PlaybackHandler:
    def __init__(self, http_client: JellyfinHttpClient, service: PlaybackService) -> None:
        self._http_client = http_client
        self._service = service

    async def handle(self, request: Request) -> Response:
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

        modified = await self._service.modify(document)
        body = json.dumps(modified, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return Response(
            content=body,
            status_code=upstream.status_code,
            headers=response_headers(upstream, content_changed=True),
            media_type="application/json",
        )
