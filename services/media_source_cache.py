"""Bounded in-memory lookup for resolved Jellyfin media source URLs."""

from __future__ import annotations

from collections import OrderedDict
from urllib.parse import urlparse


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

        self._paths[media_source_id] = path
        self._paths.move_to_end(media_source_id)
        while len(self._paths) > self._max_entries:
            self._paths.popitem(last=False)

    def get(self, media_source_id: str) -> str | None:
        path = self._paths.get(media_source_id)
        if path is not None:
            self._paths.move_to_end(media_source_id)
        return path
