"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
import tomllib
from typing import Any


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_list(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def default_config_path() -> Path:
    """Return the config beside the executable (or source tree in development)."""

    base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    return base / "JellyfinProxy.toml"


def _configured_list(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return _as_list(value)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return tuple(item.strip() for item in value if item.strip())
    raise ValueError("client list must be a string or an array of strings")


def _client_list(values: dict[str, Any], name: str) -> tuple[str, ...]:
    value: Any = os.getenv(name.upper())
    if value is None:
        value = values.get(name, [])
    return _configured_list(value)


@dataclass(frozen=True, slots=True)
class Settings:
    jellyfin_url: str
    listen_host: str
    listen_port: int
    bypass_clients: tuple[str, ...]
    playback_bypass_clients: tuple[str, ...]
    playback_cache_bypass_clients: tuple[str, ...]
    video_bypass_clients: tuple[str, ...]
    debug: bool
    request_timeout_seconds: float
    playback_info_cache_enabled: bool
    playback_info_cache_ttl_seconds: float
    playback_info_cache_max_entries: int
    log_level: str
    log_file: str
    access_log_file: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            jellyfin_url=os.getenv("JELLYFIN_URL", "http://127.0.0.1:8096").rstrip("/"),
            listen_host=os.getenv("LISTEN_HOST", "0.0.0.0"),
            listen_port=int(os.getenv("LISTEN_PORT", "8097")),
            bypass_clients=_as_list(os.getenv("BYPASS_CLIENTS", "Infuse,Kodi")),
            playback_bypass_clients=_as_list(os.getenv("PLAYBACK_BYPASS_CLIENTS", "")),
            playback_cache_bypass_clients=_as_list(os.getenv("PLAYBACK_CACHE_BYPASS_CLIENTS", "")),
            video_bypass_clients=_as_list(os.getenv("VIDEO_BYPASS_CLIENTS", "")),
            debug=_as_bool(os.getenv("DEBUG", "false")),
            request_timeout_seconds=float(os.getenv("REQUEST_TIMEOUT_SECONDS", "60")),
            playback_info_cache_enabled=_as_bool(os.getenv("PLAYBACK_INFO_CACHE_ENABLED", "true")),
            playback_info_cache_ttl_seconds=float(os.getenv("PLAYBACK_INFO_CACHE_TTL_SECONDS", "21600")),
            playback_info_cache_max_entries=int(os.getenv("PLAYBACK_INFO_CACHE_MAX_ENTRIES", "4096")),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            log_file=os.getenv("LOG_FILE", "JellyfinProxy.log"),
            access_log_file=os.getenv("ACCESS_LOG_FILE", "access.log"),
        )

    @classmethod
    def from_file(cls, path: str | Path) -> "Settings":
        """Load TOML configuration, retaining environment-variable overrides."""

        config_path = Path(path).expanduser().resolve()
        try:
            with config_path.open("rb") as config_file:
                values = tomllib.load(config_file)
        except FileNotFoundError as exc:
            raise ValueError(f"Configuration file not found: {config_path}") from exc
        except tomllib.TOMLDecodeError as exc:
            raise ValueError(f"Invalid TOML configuration: {exc}") from exc

        log_file = os.getenv("LOG_FILE", str(values.get("log_file", "JellyfinProxy.log"))).strip()
        if log_file:
            log_path = Path(log_file).expanduser()
            if not log_path.is_absolute():
                log_path = config_path.parent / log_path
            resolved_log_file = str(log_path)
        else:
            resolved_log_file = ""

        access_log_file = os.getenv(
            "ACCESS_LOG_FILE", str(values.get("access_log_file", "access.log"))
        ).strip()
        if access_log_file:
            access_log_path = Path(access_log_file).expanduser()
            if not access_log_path.is_absolute():
                access_log_path = config_path.parent / access_log_path
            resolved_access_log_file = str(access_log_path)
        else:
            resolved_access_log_file = ""

        bypass_value: Any = os.getenv("BYPASS_CLIENTS")
        if bypass_value is None:
            bypass_value = values.get("bypass_clients", ["Infuse", "Kodi"])

        return cls(
            jellyfin_url=os.getenv(
                "JELLYFIN_URL", str(values.get("jellyfin_url", "http://127.0.0.1:8096"))
            ).rstrip("/"),
            listen_host=os.getenv("LISTEN_HOST", str(values.get("listen_host", "0.0.0.0"))),
            listen_port=int(os.getenv("LISTEN_PORT", str(values.get("listen_port", 8097)))),
            bypass_clients=_configured_list(bypass_value),
            playback_bypass_clients=_client_list(values, "playback_bypass_clients"),
            playback_cache_bypass_clients=_client_list(values, "playback_cache_bypass_clients"),
            video_bypass_clients=_client_list(values, "video_bypass_clients"),
            debug=_as_bool(os.getenv("DEBUG", str(values.get("debug", False)))),
            request_timeout_seconds=float(
                os.getenv(
                    "REQUEST_TIMEOUT_SECONDS",
                    str(values.get("request_timeout_seconds", 60)),
                )
            ),
            playback_info_cache_enabled=_as_bool(
                os.getenv(
                    "PLAYBACK_INFO_CACHE_ENABLED",
                    str(values.get("playback_info_cache_enabled", True)),
                )
            ),
            playback_info_cache_ttl_seconds=float(
                os.getenv(
                    "PLAYBACK_INFO_CACHE_TTL_SECONDS",
                    str(values.get("playback_info_cache_ttl_seconds", 21600)),
                )
            ),
            playback_info_cache_max_entries=int(
                os.getenv(
                    "PLAYBACK_INFO_CACHE_MAX_ENTRIES",
                    str(values.get("playback_info_cache_max_entries", 4096)),
                )
            ),
            log_level=os.getenv("LOG_LEVEL", str(values.get("log_level", "INFO"))),
            log_file=resolved_log_file,
            access_log_file=resolved_access_log_file,
        )


settings = Settings.from_env()
