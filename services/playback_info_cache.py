"""Bounded TTL cache for completed PlaybackInfo responses."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from time import monotonic


@dataclass(frozen=True, slots=True)
class CachedPlaybackInfo:
    body: bytes


class PlaybackInfoCache:
    def __init__(self, ttl_seconds: float = 21600, max_entries: int = 4096) -> None:
        if ttl_seconds <= 0:
            raise ValueError("PlaybackInfo cache TTL must be greater than zero")
        if max_entries <= 0:
            raise ValueError("PlaybackInfo cache max entries must be greater than zero")
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._entries: OrderedDict[str, tuple[float, CachedPlaybackInfo]] = OrderedDict()

    def get(self, key: str) -> CachedPlaybackInfo | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        stored_at, response = entry
        if monotonic() - stored_at >= self._ttl_seconds:
            del self._entries[key]
            return None
        self._entries.move_to_end(key)
        return response

    def remember(self, key: str, body: bytes) -> None:
        self._entries[key] = (monotonic(), CachedPlaybackInfo(body=body))
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)
