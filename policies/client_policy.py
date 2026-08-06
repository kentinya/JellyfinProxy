"""Decide which route modifications an identified client must bypass."""

from __future__ import annotations

from collections.abc import Mapping

from routers.route_config import HandlerType


class ClientPolicy:
    HEADER_NAMES = ("user-agent", "x-emby-client", "x-emby-device-name")

    def __init__(
        self,
        bypass_clients: tuple[str, ...],
        playback_bypass_clients: tuple[str, ...] = (),
        video_bypass_clients: tuple[str, ...] = (),
        playback_cache_bypass_clients: tuple[str, ...] = (),
    ) -> None:
        self._bypass_clients = tuple(name.casefold() for name in bypass_clients)
        self._playback_bypass_clients = tuple(
            name.casefold() for name in playback_bypass_clients
        )
        self._video_bypass_clients = tuple(name.casefold() for name in video_bypass_clients)
        self._playback_cache_bypass_clients = tuple(
            name.casefold() for name in playback_cache_bypass_clients
        )

    def should_bypass_playback_cache(self, headers: Mapping[str, str]) -> bool:
        identity = " ".join(headers.get(name, "") for name in self.HEADER_NAMES).casefold()
        return any(client in identity for client in self._playback_cache_bypass_clients)

    def should_bypass(
        self,
        headers: Mapping[str, str],
        handler_type: HandlerType | None = None,
    ) -> bool:
        identity = " ".join(headers.get(name, "") for name in self.HEADER_NAMES).casefold()
        if any(client in identity for client in self._bypass_clients):
            return True
        if handler_type is HandlerType.PLAYBACK:
            return any(client in identity for client in self._playback_bypass_clients)
        if handler_type is HandlerType.VIDEO:
            return any(client in identity for client in self._video_bypass_clients)
        return False
