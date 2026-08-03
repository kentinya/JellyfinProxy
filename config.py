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
    raise ValueError("bypass_clients must be a string or an array of strings")


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
            log_file=os.getenv("LOG_FILE", "JellyfinProxy.log"),
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
            debug=_as_bool(os.getenv("DEBUG", str(values.get("debug", False)))),
            request_timeout_seconds=float(
                os.getenv(
                    "REQUEST_TIMEOUT_SECONDS",
                    str(values.get("request_timeout_seconds", 60)),
                )
            ),
            log_level=os.getenv("LOG_LEVEL", str(values.get("log_level", "INFO"))),
            log_file=resolved_log_file,
        )


settings = Settings.from_env()
