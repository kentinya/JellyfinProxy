"""Decide whether an identified client must bypass all modifications."""

from __future__ import annotations

from collections.abc import Mapping


class ClientPolicy:
    HEADER_NAMES = ("user-agent", "x-emby-client", "x-emby-device-name")

    def __init__(self, bypass_clients: tuple[str, ...]) -> None:
        self._bypass_clients = tuple(name.casefold() for name in bypass_clients)

    def should_bypass(self, headers: Mapping[str, str]) -> bool:
        identity = " ".join(headers.get(name, "") for name in self.HEADER_NAMES).casefold()
        return any(client in identity for client in self._bypass_clients)
