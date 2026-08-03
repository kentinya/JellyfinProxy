"""Analyze URLs already resolved by Jellyfin in a MediaSource."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class MediaUrl:
    """A validated HTTP(S) URL and its useful routing attributes."""

    url: str
    scheme: str
    host: str


class MediaResolver:
    """Classify an existing Path without opening files or generating URLs."""

    def analyze(self, media_path: object) -> MediaUrl | None:
        if not isinstance(media_path, str):
            return None
        parsed = urlparse(media_path)
        scheme = parsed.scheme.casefold()
        if scheme not in {"http", "https"} or not parsed.netloc:
            return None
        return MediaUrl(url=media_path, scheme=scheme, host=parsed.hostname or "")
