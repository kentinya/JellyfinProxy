"""Application configuration loaded from environment variables."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, datetime, time as datetime_time
import math
import os
from pathlib import Path
import sys
import tomllib
from typing import Any


RESERVED_RESPONSE_FIELD = "MediaSources"


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


def _type_name(value: Any) -> str:
    """Describe a configured value type without exposing the value itself."""

    if isinstance(value, datetime):
        return "datetime"
    if isinstance(value, date):
        return "date"
    if isinstance(value, datetime_time):
        return "time"
    if value is None:
        return "null"
    return type(value).__name__


def _validate_field_value(value: Any, location: str) -> None:
    """Accept only values that a standard JSON encoder can represent."""

    value_type = type(value)
    if value_type in (str, bool, int):
        return
    if value_type is float:
        if not math.isfinite(value):
            raise ValueError(
                f"Invalid configuration at {location}: unsupported non-finite number"
            )
        return
    if value_type is list:
        for index, item in enumerate(value):
            _validate_field_value(item, f"{location}[{index}]")
        return
    if value_type is dict:
        for key, item in value.items():
            if not isinstance(key, str) or key == "":
                raise ValueError(
                    f"Invalid configuration at {location}: empty field name"
                )
            _validate_field_value(item, f"{location}.{key}")
        return
    raise ValueError(
        f"Invalid configuration at {location}: unsupported type {_type_name(value)}"
    )


def _field_overrides(
    value: Any,
    location: str,
    *,
    allow_media_sources: bool,
) -> dict[str, Any]:
    """Validate one optional field table and return an independent copy."""

    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(
            f"Invalid configuration at {location}: expected a table, "
            f"found {_type_name(value)}"
        )

    overrides: dict[str, Any] = {}
    for name, field_value in value.items():
        if not isinstance(name, str) or name == "":
            raise ValueError(f"Invalid configuration at {location}: empty field name")
        if not allow_media_sources and name == RESERVED_RESPONSE_FIELD:
            raise ValueError(
                f"Invalid configuration at {location}.{name}: reserved field name; "
                "use playback_info.media_source_fields for media sources"
            )
        _validate_field_value(field_value, f"{location}.{name}")
        overrides[name] = deepcopy(field_value)
    return overrides


def _playback_info_fields(
    values: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read the two optional PlaybackInfo field tables from a TOML document."""

    playback_info = values.get("playback_info")
    if playback_info is None:
        return {}, {}
    if not isinstance(playback_info, dict):
        raise ValueError(
            "Invalid configuration at playback_info: expected a table, "
            f"found {_type_name(playback_info)}"
        )
    return (
        _field_overrides(
            playback_info.get("response_fields"),
            "playback_info.response_fields",
            allow_media_sources=False,
        ),
        _field_overrides(
            playback_info.get("media_source_fields"),
            "playback_info.media_source_fields",
            allow_media_sources=True,
        ),
    )


@dataclass(frozen=True, slots=True)
class Settings:
    jellyfin_url: str
    listen_host: str
    listen_port: int
    bypass_clients: tuple[str, ...]
    playback_bypass_clients: tuple[str, ...]
    video_bypass_clients: tuple[str, ...]
    debug: bool
    request_timeout_seconds: float
    log_level: str
    log_file: str
    access_log_file: str
    playback_info_response_fields: dict[str, Any] = field(default_factory=dict)
    playback_info_media_source_fields: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            jellyfin_url=os.getenv("JELLYFIN_URL", "http://127.0.0.1:8096").rstrip("/"),
            listen_host=os.getenv("LISTEN_HOST", "0.0.0.0"),
            listen_port=int(os.getenv("LISTEN_PORT", "8097")),
            bypass_clients=_as_list(os.getenv("BYPASS_CLIENTS", "Infuse,Kodi")),
            playback_bypass_clients=_as_list(os.getenv("PLAYBACK_BYPASS_CLIENTS", "")),
            video_bypass_clients=_as_list(os.getenv("VIDEO_BYPASS_CLIENTS", "")),
            debug=_as_bool(os.getenv("DEBUG", "false")),
            request_timeout_seconds=float(os.getenv("REQUEST_TIMEOUT_SECONDS", "60")),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            log_file=os.getenv("LOG_FILE", "JellyfinProxy.log"),
            access_log_file=os.getenv("ACCESS_LOG_FILE", "access.log"),
            playback_info_response_fields={},
            playback_info_media_source_fields={},
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

        response_fields, media_source_fields = _playback_info_fields(values)

        return cls(
            jellyfin_url=os.getenv(
                "JELLYFIN_URL", str(values.get("jellyfin_url", "http://127.0.0.1:8096"))
            ).rstrip("/"),
            listen_host=os.getenv("LISTEN_HOST", str(values.get("listen_host", "0.0.0.0"))),
            listen_port=int(os.getenv("LISTEN_PORT", str(values.get("listen_port", 8097)))),
            bypass_clients=_configured_list(bypass_value),
            playback_bypass_clients=_client_list(values, "playback_bypass_clients"),
            video_bypass_clients=_client_list(values, "video_bypass_clients"),
            debug=_as_bool(os.getenv("DEBUG", str(values.get("debug", False)))),
            request_timeout_seconds=float(
                os.getenv(
                    "REQUEST_TIMEOUT_SECONDS",
                    str(values.get("request_timeout_seconds", 60)),
                )
            ),
            log_level=os.getenv("LOG_LEVEL", str(values.get("log_level", "INFO"))),
            log_file=resolved_log_file,
            access_log_file=resolved_access_log_file,
            playback_info_response_fields=response_fields,
            playback_info_media_source_fields=media_source_fields,
        )


settings = Settings.from_env()
