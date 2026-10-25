"""Apply narrowly scoped modifications to Jellyfin PlaybackInfo documents."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import logging
from typing import Any

from services.media_source_service import MediaSourceAction, MediaSourceService
from services.media_source_cache import MediaSourceCache


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PlaybackFieldOverrides:
    """Explicit PlaybackInfo field values configured by the user.

    Both collections are empty by default, which means that no field is changed.
    """

    response_fields: dict[str, Any] = field(default_factory=dict)
    media_source_fields: dict[str, Any] = field(default_factory=dict)


class PlaybackService:
    def __init__(
        self,
        media_source_service: MediaSourceService,
        media_source_cache: MediaSourceCache | None = None,
        field_overrides: PlaybackFieldOverrides | None = None,
    ) -> None:
        self._media_source_service = media_source_service
        self.media_source_cache = media_source_cache or MediaSourceCache()
        self._field_overrides = field_overrides or PlaybackFieldOverrides()

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

        # Explicit root fields are applied before the media source pipeline.
        for name, value in self._field_overrides.response_fields.items():
            playback_info[name] = deepcopy(value)

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
            if self._field_overrides.media_source_fields:
                # Only sources whose configured-path was recognized before this
                # stage may receive the explicit media source field values.
                if self._media_source_service.is_usable_remote(source.get("Path")):
                    original_id = source.get("Id")
                    source.update(deepcopy(self._field_overrides.media_source_fields))
                    if source.get("Id") != original_id:
                        self.media_source_cache.forget(original_id)
            self.media_source_cache.remember(source.get("Id"), source.get("Path"))
        logger.info(
            "playback_info_processed media_sources=%d modified=%d",
            len(media_sources),
            modified_count,
        )
        return playback_info
