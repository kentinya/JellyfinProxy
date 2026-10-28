from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import httpx
from fastapi import Request

from handlers.dispatcher import CLIENT_HEADER_LIMIT, Dispatcher, _safe_client_header
from infrastructure.logging import bind_request_id, configure_logging, log_access, reset_request_id
from config import Settings
from main import _request_id, create_app
from policies.client_policy import ClientPolicy
from routers.router import Router
from services.media_resolver import MediaResolver
from services.media_source_service import MediaSourceService
from services.playback_service import PlaybackService


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


def test_access_logs_are_written_separately_and_redacted(tmp_path: Path) -> None:
    service_log = tmp_path / "JellyfinProxy.log"
    access_log = tmp_path / "access.log"
    configure_logging("INFO", str(service_log), str(access_log))

    log_access(
        method="GET",
        path="/Items?api_key=secret&deviceId=safe",
        status_code=200,
        duration_ms=12.34,
        client_ip="127.0.0.1",
    )

    output = access_log.read_text(encoding="utf-8")
    assert '【Access】' in output
    assert '200 | 12.34ms | GET' in output
    assert '127.0.0.1 "/Items?api_key=[REDACTED]&deviceId=safe"' in output
    assert "secret" not in output
    assert "【Access】" not in service_log.read_text(encoding="utf-8")


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


def test_client_identity_headers_are_safe_and_bounded() -> None:
    value = "Infuse\r\nforged-log" + ("x" * 300)
    cleaned = _safe_client_header(value)
    assert "\r" not in cleaned
    assert "\n" not in cleaned
    assert "Infuse  forged-log" in cleaned
    assert len(cleaned) == CLIENT_HEADER_LIMIT


def test_playback_request_logging_has_no_cache_diagnostics(capsys) -> None:
    class FakeClient:
        async def forward(self, request: Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "MediaSources": [{
                        "Id": "source-id",
                        "Path": "https://media.example/movie.mkv",
                    }]
                },
            )

    configure_logging("INFO")
    dispatcher = Dispatcher(
        router=Router(),
        client_policy=ClientPolicy((), playback_bypass_clients=("PlaybackOnly",)),
        http_client=FakeClient(),  # type: ignore[arg-type]
        playback_service=PlaybackService(MediaSourceService(MediaResolver())),
    )
    request = Request({
        "type": "http",
        "method": "POST",
        "scheme": "http",
        "server": ("proxy", 8097),
        "path": "/Items/item-id/PlaybackInfo",
        "query_string": b"api_key=secret",
        "headers": [
            (b"x-emby-client", b"CacheOnly"),
            (b"x-emby-device-name", b"Living Room"),
            (b"x-emby-device-id", b"device-id"),
        ],
    })

    token = bind_request_id("log-request-id")
    try:
        response = asyncio.run(dispatcher.dispatch(request))
    finally:
        reset_request_id(token)

    output = capsys.readouterr().out
    assert "client_identified route=playback action=modify" in output
    assert "cache=" not in output
    assert "playback_info_cache" not in output
    assert "request_id=log-request-id" in output
    assert "emby_client='CacheOnly'" in output
    assert "device_name='Living Room'" in output
    assert "secret" not in output
    # The former cache-bypass client is no longer special in any way.
    assert "x-jellyfinproxy-cache" not in response.headers


class _VideoBody(httpx.AsyncByteStream):
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.closed = False

    async def __aiter__(self):
        if self.body:
            yield self.body

    async def aclose(self) -> None:
        self.closed = True


class _VideoUpstream:
    def __init__(self, status_code=200, headers=None, body=b"") -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self.body = body
        self.stream_calls: list[Request] = []
        self.streams: list[_VideoBody] = []

    async def forward_stream(self, request: Request) -> httpx.Response:
        self.stream_calls.append(request)
        stream = _VideoBody(self.body)
        self.streams.append(stream)
        return httpx.Response(self.status_code, headers=self.headers, stream=stream)


def _video_logging_dispatcher(upstream, **policy_kwargs):
    service = PlaybackService(MediaSourceService(MediaResolver()))
    dispatcher = Dispatcher(
        router=Router(),
        client_policy=ClientPolicy((), **policy_kwargs),
        http_client=upstream,  # type: ignore[arg-type]
        playback_service=service,
    )
    return dispatcher, service.media_source_cache


def _video_request(
    method: str = "GET",
    path: str = "/Videos/item/stream.mkv",
    query: bytes = b"",
    headers: list[tuple[bytes, bytes]] | None = None,
) -> Request:
    return Request({
        "type": "http",
        "method": method,
        "scheme": "http",
        "server": ("proxy", 8097),
        "path": path,
        "query_string": query,
        "headers": headers or [],
    })


async def _dispatch_and_drain(dispatcher: Dispatcher, request: Request):
    response = await dispatcher.dispatch(request)
    body_iterator = getattr(response, "body_iterator", None)
    if body_iterator is not None:
        async for _ in body_iterator:
            pass
    return response


def test_s2_1_logging_video_get_redirect_reports_hit_and_redacts_credentials(capsys) -> None:
    secret = "s2-1-secret-token"
    signed_url = f"https://media.example/movie.mkv?token={secret}&signature=abc"
    upstream = _VideoUpstream()
    dispatcher, cache = _video_logging_dispatcher(upstream)
    cache.remember("source-id", signed_url)
    request = _video_request(
        query=f"MediaSourceId=source-id&api_key={secret}".encode(),
        headers=[
            (b"cookie", f"session={secret}".encode()),
            (b"authorization", f"Bearer {secret}".encode()),
        ],
    )

    configure_logging("INFO")
    token = bind_request_id("s2-1-log-hit")
    try:
        response = asyncio.run(_dispatch_and_drain(dispatcher, request))
    finally:
        reset_request_id(token)

    output = capsys.readouterr().out
    assert response.status_code == 302
    assert response.headers["location"] == signed_url
    assert upstream.stream_calls == []
    assert "request_id=s2-1-log-hit" in output
    assert "method=GET" in output
    assert "handling=redirect" in output
    assert "mapping=hit" in output
    assert "status=302" in output
    assert secret not in output
    assert "media.example" not in output


def test_s2_1_logging_video_head_reports_proxy_without_mapping_query(capsys) -> None:
    upstream = _VideoUpstream(
        200,
        {"content-length": "12345", "content-type": "video/mp4"},
    )
    dispatcher, cache = _video_logging_dispatcher(upstream)
    cache.remember("source-id", "https://media.example/movie.mkv")
    request = _video_request(method="HEAD", query=b"MediaSourceId=source-id")

    configure_logging("INFO")
    token = bind_request_id("s2-1-log-head")
    try:
        response = asyncio.run(_dispatch_and_drain(dispatcher, request))
    finally:
        reset_request_id(token)

    output = capsys.readouterr().out
    assert response.status_code == 200
    assert upstream.stream_calls[0].method == "HEAD"
    assert "request_id=s2-1-log-head" in output
    assert "method=HEAD" in output
    assert "handling=proxy" in output
    assert "mapping=not_queried" in output
    assert "status=200" in output
    assert "mapping=hit" not in output


def test_s2_1_logging_video_miss_does_not_report_upstream_redirect_as_hit(capsys) -> None:
    upstream = _VideoUpstream(
        302,
        {"location": "https://jellyfin.example/upstream-redirect"},
    )
    dispatcher, _ = _video_logging_dispatcher(upstream)
    request = _video_request(query=b"MediaSourceId=missing-id")

    configure_logging("INFO")
    token = bind_request_id("s2-1-log-miss")
    try:
        response = asyncio.run(_dispatch_and_drain(dispatcher, request))
    finally:
        reset_request_id(token)

    output = capsys.readouterr().out
    assert response.status_code == 302
    assert response.headers["location"] == "https://jellyfin.example/upstream-redirect"
    assert "request_id=s2-1-log-miss" in output
    assert "handling=proxy" in output
    assert "mapping=miss" in output
    assert "status=302" in output
    assert "mapping=hit" not in output


def test_s2_1_logging_video_bypass_reports_proxy_without_mapping_query(capsys) -> None:
    upstream = _VideoUpstream(206, {"content-range": "bytes 0-8/100"}, b"media-bytes")
    dispatcher, cache = _video_logging_dispatcher(
        upstream,
        video_bypass_clients=("VideoBypass",),
    )
    cache.remember("source-id", "https://media.example/movie.mkv")
    request = _video_request(
        query=b"MediaSourceId=source-id",
        headers=[(b"x-emby-client", b"VideoBypass")],
    )

    configure_logging("INFO")
    token = bind_request_id("s2-1-log-bypass")
    try:
        response = asyncio.run(_dispatch_and_drain(dispatcher, request))
    finally:
        reset_request_id(token)

    output = capsys.readouterr().out
    assert response.status_code == 206
    assert upstream.stream_calls[0].method == "GET"
    assert "request_id=s2-1-log-bypass" in output
    assert "method=GET" in output
    assert "handling=proxy" in output
    assert "mapping=not_queried" in output
    assert "status=206" in output
    assert "reason=client_bypass" in output
    assert "mapping=hit" not in output
