"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_list(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


@dataclass(frozen=True, slots=True)
class Settings:
    jellyfin_url: str
    listen_host: str
    listen_port: int
    bypass_clients: tuple[str, ...]
    debug: bool
    request_timeout_seconds: float
    log_level: str
    log_file: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            jellyfin_url=os.getenv("JELLYFIN_URL", "http://127.0.0.1:8096").rstrip("/"),
            listen_host=os.getenv("LISTEN_HOST", "0.0.0.0"),
            listen_port=int(os.getenv("LISTEN_PORT", "8097")),
            bypass_clients=_as_list(os.getenv("BYPASS_CLIENTS", "Infuse,Kodi")),
            debug=_as_bool(os.getenv("DEBUG", "false")),
            request_timeout_seconds=float(os.getenv("REQUEST_TIMEOUT_SECONDS", "60")),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            log_file=os.getenv("LOG_FILE", "mediawarp.log"),
        )


settings = Settings.from_env()
