"""Application logging configuration and request context."""

from __future__ import annotations

import logging
import re
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from contextvars import ContextVar, Token


_request_id: ContextVar[str] = ContextVar("request_id", default="-")
_access_logger = logging.getLogger("jellyfinproxy.access")
_SENSITIVE_QUERY_VALUE = re.compile(
    r"(?i)(api_key|x-emby-token|access_token|token)=([^&\s\"]+)"
)


class RedactingFormatter(logging.Formatter):
    """Redact credentials even when dependency logs include full URLs."""

    def format(self, record: logging.LogRecord) -> str:
        rendered = super().format(record)
        return _SENSITIVE_QUERY_VALUE.sub(r"\1=[REDACTED]", rendered)


class RequestContextFilter(logging.Filter):
    """Attach the current request ID to every emitted record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()  # type: ignore[attr-defined]
        return True


def _rotating_file_handler(path_value: str) -> RotatingFileHandler:
    path = Path(path_value).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    return RotatingFileHandler(
        path,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )


def configure_logging(
    level: str,
    log_file: str | None = None,
    access_log_file: str | None = None,
) -> None:
    """Configure one consistent, dependency-free application log format."""

    normalized_level = level.strip().upper()
    numeric_level = getattr(logging, normalized_level, None)
    if not isinstance(numeric_level, int):
        raise ValueError(f"Unsupported LOG_LEVEL: {level!r}")

    formatter = RedactingFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s request_id=%(request_id)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    context_filter = RequestContextFilter()

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        handlers.append(_rotating_file_handler(log_file))

    for handler in handlers:
        handler.addFilter(context_filter)
        handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    for handler in handlers:
        root_logger.addHandler(handler)
    root_logger.setLevel(numeric_level)

    # These libraries include the full query string in INFO logs, which may
    # expose Jellyfin API keys. Application request logs intentionally do not.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    # Access records have their own file, matching MediaWarp's separation of
    # service and access logs. They do not propagate into the application log.
    _access_logger.handlers.clear()
    _access_logger.propagate = False
    _access_logger.setLevel(numeric_level)
    if access_log_file:
        access_handler = _rotating_file_handler(access_log_file)
        access_handler.setFormatter(RedactingFormatter("%(message)s"))
        _access_logger.addHandler(access_handler)


def log_access(
    *,
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
    client_ip: str,
) -> None:
    """Write one MediaWarp-style access record to the dedicated access log."""

    _access_logger.info(
        '【Access】 %s | %d | %.2fms | %-7s | %s "%s"',
        datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"),
        status_code,
        duration_ms,
        method,
        client_ip,
        path,
    )


def bind_request_id(request_id: str) -> Token[str]:
    return _request_id.set(request_id)


def reset_request_id(token: Token[str]) -> None:
    _request_id.reset(token)
