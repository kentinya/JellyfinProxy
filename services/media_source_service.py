"""Policy engine for Jellyfin MediaSource decisions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from services.media_resolver import MediaResolver, MediaUrl


class MediaSourceAction(str, Enum):
    PASSTHROUGH = "passthrough"
    REWRITE = "rewrite"
    REDIRECT = "redirect"
    PROXY = "proxy"


@dataclass(frozen=True, slots=True)
class MediaSourceDecision:
    action: MediaSourceAction
    url: str | None = None
    field_updates: Mapping[str, Any] | None = None


class MediaSourceRule(Protocol):
    """Extension point for rewrite, redirect, and proxy policies."""

    def evaluate(
        self,
        source: Mapping[str, Any],
        media_url: MediaUrl,
    ) -> MediaSourceDecision | None: ...


class ProtocolFileRule:
    """Present remote URLs as File sources and disable transcoding."""

    def evaluate(
        self,
        source: Mapping[str, Any],
        media_url: MediaUrl,
    ) -> MediaSourceDecision:
        del source
        return MediaSourceDecision(
            action=MediaSourceAction.REWRITE,
            url=media_url.url,
            field_updates={
                "Protocol": "File",
                "SupportsTranscoding": False,
            },
        )


class MediaSourceService:
    def __init__(
        self,
        resolver: MediaResolver,
        rules: Sequence[MediaSourceRule] = (),
    ) -> None:
        self._resolver = resolver
        self._rules = tuple(rules)

    @property
    def rules(self) -> tuple[MediaSourceRule, ...]:
        """The configured policy rules, empty when only passthrough applies."""

        return self._rules

    def decide(self, source: Mapping[str, Any]) -> MediaSourceDecision:
        media_url = self._resolver.analyze(source.get("Path"))
        if media_url is None:
            return MediaSourceDecision(MediaSourceAction.PASSTHROUGH)

        for rule in self._rules:
            decision = rule.evaluate(source, media_url)
            if decision is not None:
                return decision

        return MediaSourceDecision(MediaSourceAction.PASSTHROUGH, media_url.url)

    def is_usable_remote(self, media_path: object) -> bool:
        """Report whether the given existing Path is a usable HTTP(S) URL."""

        return self._resolver.analyze(media_path) is not None
