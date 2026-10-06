"""Apply narrowly scoped modifications to Jellyfin PlaybackInfo documents."""

from __future__ import annotations

import logging
from typing import Any

from services.media_source_service import MediaSourceAction, MediaSourceService
from services.media_source_cache import MediaSourceCache


logger = logging.getLogger(__name__)


class PlaybackService:
    def __init__(
        self,
        media_source_service: MediaSourceService,
        media_source_cache: MediaSourceCache | None = None,
    ) -> None:
        self._media_source_service = media_source_service
        self.media_source_cache = media_source_cache or MediaSourceCache()

    def remember_media_sources(self, playback_info: Any) -> None:
        """Record redirect URLs without applying policies or changing the response."""
        if not isinstance(playback_info, dict):
            return
        media_sources = playback_info.get("MediaSources")
        if not isinstance(media_sources, list):
            return
        for source in media_sources:
            if isinstance(source, dict):
                self.media_source_cache.remember(source.get("Id"), source.get("Path"))

    async def modify(self, playback_info: Any) -> Any:
        if not isinstance(playback_info, dict):
            return playback_info
        media_sources = playback_info.get("MediaSources")
        if not isinstance(media_sources, list):
            return playback_info

        modified_count = 0
        for source in media_sources:
            if not isinstance(source, dict):
                continue
            decision = self._media_source_service.decide(source)
            if decision.action is not MediaSourceAction.PASSTHROUGH:
                if decision.url is not None:
                    source["Path"] = decision.url
                if decision.field_updates is not None:
                    source.update(decision.field_updates)
                modified_count += 1
            self.media_source_cache.remember(source.get("Id"), source.get("Path"))
        logger.info(
            "playback_info_processed media_sources=%d modified=%d",
            len(media_sources),
            modified_count,
        )
        return playback_info
