"""Application logging configuration and request context."""

from __future__ import annotations

import logging
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from contextvars import ContextVar, Token


_request_id: ContextVar[str] = ContextVar("request_id", default="-")
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


def configure_logging(level: str, log_file: str | None = None) -> None:
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
        path = Path(log_file).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                path,
                maxBytes=10 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
        )

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


def bind_request_id(request_id: str) -> Token[str]:
    return _request_id.set(request_id)


def reset_request_id(token: Token[str]) -> None:
    _request_id.reset(token)
