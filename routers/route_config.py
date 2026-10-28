"""Declarative route rules. Add future interception points here."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from re import IGNORECASE, Pattern, compile


class HandlerType(str, Enum):
    PLAYBACK = "playback"
    VIDEO = "video"
    DEFAULT = "default"


@dataclass(frozen=True, slots=True)
class RouteRule:
    name: str
    pattern: Pattern[str]
    handler_type: HandlerType
    methods: frozenset[str] | None = None


ROUTE_RULES: tuple[RouteRule, ...] = (
    RouteRule(
        name="playback_info",
        pattern=compile(r"^/(?:emby/)?Items/([^/]+)/PlaybackInfo/?$", flags=0),
        handler_type=HandlerType.PLAYBACK,
        methods=frozenset({"GET", "POST"}),
    ),
    RouteRule(
        name="video",
        pattern=compile(
            r"^/videos/[^/]+/stream(?:\.[^/]+)?$",
            flags=IGNORECASE,
        ),
        handler_type=HandlerType.VIDEO,
        methods=frozenset({"GET", "HEAD"}),
    ),
    RouteRule(name="default", pattern=compile(r".*", flags=0), handler_type=HandlerType.DEFAULT),
)
