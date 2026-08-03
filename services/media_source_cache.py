"""Bounded in-memory lookup for resolved Jellyfin media source URLs."""

from __future__ import annotations

from collections import OrderedDict
from urllib.parse import urlparse


def _normalize_media_source_id(value: str) -> str:
    compact = value.replace("-", "")
    if len(compact) == 32 and all(character in "0123456789abcdefABCDEF" for character in compact):
        return compact.casefold()
    return value


class MediaSourceCache:
    def __init__(self, max_entries: int = 4096) -> None:
        self._max_entries = max_entries
        self._paths: OrderedDict[str, str] = OrderedDict()

    def remember(self, media_source_id: object, path: object) -> None:
        if not isinstance(media_source_id, str) or not media_source_id:
            return
        if not isinstance(path, str):
            return
        parsed = urlparse(path)
        if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
            return

        cache_key = _normalize_media_source_id(media_source_id)
        self._paths[cache_key] = path
        self._paths.move_to_end(cache_key)
        while len(self._paths) > self._max_entries:
            self._paths.popitem(last=False)

    def get(self, media_source_id: str) -> str | None:
        cache_key = _normalize_media_source_id(media_source_id)
        path = self._paths.get(cache_key)
        if path is not None:
            self._paths.move_to_end(cache_key)
        return path
