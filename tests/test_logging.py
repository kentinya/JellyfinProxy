from __future__ import annotations

import logging
from pathlib import Path

from fastapi import Request

from infrastructure.logging import bind_request_id, configure_logging, reset_request_id
from config import Settings
from main import _request_id, create_app


def test_log_records_include_bound_request_id(capsys) -> None:
    configure_logging("INFO")
    token = bind_request_id("test-request-id")
    try:
        logging.getLogger("test").info("message")
    finally:
        reset_request_id(token)

    output = capsys.readouterr().out
    assert "request_id=test-request-id" in output
    assert "message" in output


def test_logs_are_written_to_file(tmp_path: Path) -> None:
    log_file = tmp_path / "JellyfinProxy.log"
    configure_logging("INFO", str(log_file))
    logging.getLogger("test").info("file_message")
    assert "file_message" in log_file.read_text(encoding="utf-8")


def test_sensitive_query_values_are_redacted(tmp_path: Path) -> None:
    log_file = tmp_path / "JellyfinProxy.log"
    configure_logging("INFO", str(log_file))
    logging.getLogger("test").warning(
        'WebSocket /socket?api_key=secret&deviceId=safe'
    )
    output = log_file.read_text(encoding="utf-8")
    assert "secret" not in output
    assert "api_key=[REDACTED]" in output


def _request_with_id(value: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"x-request-id", value.encode("latin-1"))],
    })


def test_request_id_preserves_safe_values_and_replaces_unsafe_values() -> None:
    assert _request_id(_request_with_id("safe-id:123")) == "safe-id:123"
    generated = _request_id(_request_with_id("unsafe id"))
    assert generated != "unsafe id"
    assert len(generated) == 32


def test_response_middleware_version_uses_configured_app() -> None:
    app = create_app(Settings.from_env())
    assert app.version
