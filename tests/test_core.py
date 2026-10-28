from __future__ import annotations

import asyncio
import gzip
import json
from dataclasses import replace
from unittest.mock import patch

import httpx
import pytest
from fastapi import Request, Response
from starlette.testclient import TestClient

import main as main_module
from config import Settings
from handlers.video_handler import VideoHandler
from handlers.playback_handler import PlaybackHandler
from handlers.proxy_handler import ProxyHandler, response_headers, streaming_response_headers
from policies.client_policy import ClientPolicy
from routers.route_config import HandlerType
from routers.router import Router
from services.media_resolver import MediaResolver
from services.media_source_cache import MediaSourceCache
from services.media_source_service import (
    MediaSourceAction,
    MediaSourceDecision,
    MediaSourceService,
    ProtocolFileRule,
)
from services.playback_service import PlaybackFieldOverrides, PlaybackService


class RewriteRule:
    def evaluate(self, source, media_url):
        if media_url.host == "alist.example.com":
            return MediaSourceDecision(
                MediaSourceAction.REWRITE,
                media_url.url.replace("alist.example.com", "cdn.example.com"),
            )
        return None


def test_playback_handler_forwards_every_request_and_returns_own_response() -> None:
    class TransactionClient:
        def __init__(self) -> None:
            self.calls: list[Request] = []

        async def forward(self, request: Request) -> httpx.Response:
            self.calls.append(request)
            transaction = len(self.calls)
            return httpx.Response(
                200,
                json={
                    "transaction": transaction,
                    "MediaSources": [{
                        "Id": f"source-{transaction}",
                        "Path": f"https://media.example/{transaction}.mkv",
                    }],
                },
            )

    def request(
        device_id: bytes = b"android-device",
        body: bytes = b'{"DeviceProfile":{"Name":"Android"}}',
        api_key: bytes = b"first-token",
        path: str = "/Items/c7abcb3401d22d5cd3fd058cc914bdcf/PlaybackInfo",
    ) -> Request:
        sent = False

        async def receive():
            nonlocal sent
            if sent:
                return {"type": "http.disconnect"}
            sent = True
            return {"type": "http.request", "body": body}

        return Request({
            "type": "http",
            "method": "POST",
            "scheme": "http",
            "server": ("proxy", 8097),
            "path": path,
            "query_string": b"UserId=user-id&api_key=" + api_key,
            "headers": [(b"x-emby-device-id", device_id)],
        }, receive)

    client = TransactionClient()
    handler = PlaybackHandler(
        client,  # type: ignore[arg-type]
        PlaybackService(MediaSourceService(MediaResolver())),
    )

    first = asyncio.run(handler.handle(request()))
    second = asyncio.run(handler.handle(request(
        device_id=b"television-device",
        body=b'{"DeviceProfile":{"Name":"Android TV"}}',
        api_key=b"second-token",
        path="/emby/Items/c7abcb34-01d2-2d5c-d3fd-058cc914bdcf/PlaybackInfo",
    )))

    assert len(client.calls) == 2
    first_upstream, second_upstream = client.calls
    assert first_upstream.url.path == "/Items/c7abcb3401d22d5cd3fd058cc914bdcf/PlaybackInfo"
    assert second_upstream.url.path == "/emby/Items/c7abcb34-01d2-2d5c-d3fd-058cc914bdcf/PlaybackInfo"
    assert first_upstream.url.query == "UserId=user-id&api_key=first-token"
    assert second_upstream.url.query == "UserId=user-id&api_key=second-token"
    assert first_upstream.headers["x-emby-device-id"] == "android-device"
    assert second_upstream.headers["x-emby-device-id"] == "television-device"

    # Each response carries the transaction of its own upstream call.
    assert json.loads(first.body)["transaction"] == 1
    assert json.loads(second.body)["transaction"] == 2
    assert json.loads(first.body)["MediaSources"][0]["Id"] == "source-1"
    assert json.loads(second.body)["MediaSources"][0]["Id"] == "source-2"
    assert first.body != second.body
    assert "x-jellyfinproxy-cache" not in first.headers
    assert "x-jellyfinproxy-cache" not in second.headers


def test_bypassed_playback_preserves_body_and_populates_video_redirect() -> None:
    original = b'{ "MediaSources": [{"Id":"source-id", "Path":"https://media.example/movie.mkv", "Protocol":"Http", "SupportsTranscoding":true}] }'

    class Client:
        calls = 0

        async def forward(self, request):
            self.calls += 1
            return httpx.Response(200, content=original, headers={"content-type": "application/json"})

    def request(path, query=b""):
        return Request({
            "type": "http", "method": "GET", "scheme": "http",
            "server": ("proxy", 8097), "path": path,
            "query_string": query, "headers": [(b"user-agent", b"Hills Windows/1.5.4")],
        })

    client = Client()
    service = PlaybackService(MediaSourceService(MediaResolver(), [ProtocolFileRule()]))
    handler = PlaybackHandler(client, service)
    response = asyncio.run(handler.handle(
        request("/Items/item-id/PlaybackInfo"), modify=False,
    ))
    assert response.body == original
    assert client.calls == 1
    assert "x-jellyfinproxy-cache" not in response.headers

    class UnexpectedProxy:
        async def handle(self, request):
            pytest.fail("Video should redirect instead of reaching Jellyfin")

    video = VideoHandler(UnexpectedProxy(), service.media_source_cache)
    redirect = asyncio.run(video.handle(request(
        "/Videos/item-id/stream.mkv", b"mediaSourceId=source-id",
    )))
    assert redirect.status_code == 302
    assert redirect.headers["location"] == "https://media.example/movie.mkv"


OLD_VIDEO_URL = "https://media.example/old.mkv"


class PlaybackPipeline:
    """Minimal fake-upstream pipeline that exposes the real handler chain."""

    def __init__(self, body: bytes, *, status_code: int = 200) -> None:
        self.body = body
        self.status_code = status_code
        self.calls = 0
        self.service = PlaybackService(
            MediaSourceService(MediaResolver(), [ProtocolFileRule()]),
        )
        self.handler = PlaybackHandler(self, self.service)  # type: ignore[arg-type]

    async def forward(self, request: Request) -> httpx.Response:
        self.calls += 1
        return httpx.Response(
            self.status_code,
            content=self.body,
            headers={"content-type": "application/json"},
        )

    def request(self, path: str = "/Items/item-id/PlaybackInfo", query: bytes = b"") -> Request:
        return Request({
            "type": "http", "method": "GET", "scheme": "http",
            "server": ("proxy", 8097), "path": path,
            "query_string": query, "headers": [],
        })

    def playback(self, *args, **kwargs) -> Response:
        return asyncio.run(self.handler.handle(*args, **kwargs))


INVALID_PIPELINE_PATHS = [
    pytest.param("/media/movie.mkv", id="local-path"),
    pytest.param("", id="empty-path"),
    pytest.param(None, id="none-path"),
    pytest.param("ftp://media.example/movie.mkv", id="ftp-scheme"),
    pytest.param("https:///movie.mkv", id="missing-netloc"),
    pytest.param("http://", id="scheme-only"),
]


def playback_document(path, media_source_id: str = "source-id") -> bytes:
    source: dict[str, object] = {"Id": media_source_id}
    if path is not None:
        source["Path"] = path
    return json.dumps({"MediaSources": [source]}).encode("utf-8")


@pytest.mark.parametrize("modify", [True, False])
@pytest.mark.parametrize("path", INVALID_PIPELINE_PATHS)
def test_playback_pipeline_clears_stale_mapping_for_invalid_path(
    modify, path
) -> None:
    body = playback_document(path)
    pipeline = PlaybackPipeline(body)
    pipeline.service.media_source_cache.remember("source-id", OLD_VIDEO_URL)

    response = pipeline.playback(pipeline.request(), modify=modify)
    assert pipeline.calls == 1
    assert "x-jellyfinproxy-cache" not in response.headers

    assert pipeline.service.media_source_cache.get("source-id") is None
    if modify:
        returned = json.loads(response.body)["MediaSources"][0]
        assert returned.get("Path") in (None, path)
    else:
        assert response.body == body

    class RecordingProxy:
        calls = 0

        async def handle(self, request: Request) -> Response:
            self.calls += 1
            return Response(content=b"media-bytes", status_code=206)

    proxy = RecordingProxy()
    video = VideoHandler(proxy, pipeline.service.media_source_cache)  # type: ignore[arg-type]
    video_request = pipeline.request(
        "/Videos/source-id/stream.mkv",
        b"MediaSourceId=source-id",
    )
    played = asyncio.run(video.handle(video_request))
    assert proxy.calls == 1
    assert played.status_code == 206
    assert played.body == b"media-bytes"
    assert "location" not in played.headers


def test_playback_pipeline_keeps_other_media_source_mapping() -> None:
    body = playback_document("/media/movie.mkv", "source-a")
    pipeline = PlaybackPipeline(body)
    pipeline.service.media_source_cache.remember("source-a", OLD_VIDEO_URL)
    pipeline.service.media_source_cache.remember("source-b", "https://media.example/b.mkv")

    pipeline.playback(pipeline.request(), modify=False)

    assert pipeline.service.media_source_cache.get("source-a") is None
    assert pipeline.service.media_source_cache.get("source-b") == "https://media.example/b.mkv"


def test_playback_pipeline_restores_redirect_after_new_valid_path() -> None:
    pipeline = PlaybackPipeline(playback_document("/media/movie.mkv"))
    pipeline.service.media_source_cache.remember("source-id", OLD_VIDEO_URL)
    pipeline.playback(pipeline.request(), modify=False)
    assert pipeline.service.media_source_cache.get("source-id") is None

    restored = PlaybackPipeline(playback_document("https://media.example/new.mkv"))
    restored.service.media_source_cache.remember("source-id", OLD_VIDEO_URL)
    restored.playback(restored.request(), modify=False)

    class UnexpectedProxy:
        async def handle(self, request: Request) -> Response:
            pytest.fail("Video should redirect after a new valid path")

    for path, query in (
        ("/Videos/source-id/stream.mkv", b"MediaSourceId=source-id"),
        ("/videos/source-id/stream.mkv", b"mediaSourceId=source-id"),
        ("/Videos/source-id/stream", b""),
    ):
        response = asyncio.run(
            VideoHandler(UnexpectedProxy(), restored.service.media_source_cache).handle(  # type: ignore[arg-type]
                restored.request(path, query),
            )
        )
        assert response.status_code == 302
        assert response.headers["location"] == "https://media.example/new.mkv"


@pytest.mark.parametrize(("video_path", "query"), [
    pytest.param("/Videos/source-id/stream.mkv", b"MediaSourceId=source-id", id="query-media-source-id"),
    pytest.param("/videos/source-id/stream.mkv", b"mediaSourceId=source-id", id="query-lower-media-source-id"),
    pytest.param("/Videos/source-id/stream", b"", id="videos-path-id"),
    pytest.param("/Videos/788be25d-f930-7eb4-19a2-316de9f9d699/stream", b"", id="videos-path-uuid"),
])
def test_playback_pipeline_video_falls_back_to_proxy_after_clearing(video_path, query) -> None:
    media_source_id = (
        "788be25df9307eb419a2316de9f9d699" if "788be25d" in video_path else "source-id"
    )
    pipeline = PlaybackPipeline(playback_document(None, media_source_id))
    pipeline.service.media_source_cache.remember(media_source_id, OLD_VIDEO_URL)
    pipeline.playback(pipeline.request(), modify=False)
    assert pipeline.service.media_source_cache.get(media_source_id) is None

    recorded: list[str] = []

    class RecordingProxy:
        async def handle(self, request: Request) -> Response:
            recorded.append(request.url.path)
            return Response(content=b"proxied", status_code=200)

    response = asyncio.run(
        VideoHandler(RecordingProxy(), pipeline.service.media_source_cache).handle(  # type: ignore[arg-type]
            pipeline.request(video_path, query),
        )
    )

    assert recorded == [video_path]
    assert response.status_code == 200
    assert response.body == b"proxied"


@pytest.mark.parametrize("status_code", [401, 500])
def test_playback_pipeline_upstream_failure_keeps_mappings(status_code) -> None:
    pipeline = PlaybackPipeline(b'{"MediaSources": []}', status_code=status_code)
    pipeline.service.media_source_cache.remember("source-id", OLD_VIDEO_URL)

    response = pipeline.playback(pipeline.request(), modify=True)

    assert response.status_code == status_code
    assert pipeline.service.media_source_cache.get("source-id") == OLD_VIDEO_URL


def test_playback_pipeline_unparsable_json_keeps_mappings() -> None:
    pipeline = PlaybackPipeline(b"not-json")
    pipeline.service.media_source_cache.remember("source-id", OLD_VIDEO_URL)

    response = pipeline.playback(pipeline.request(), modify=True)

    assert response.status_code == 200
    assert response.body == b"not-json"
    assert pipeline.service.media_source_cache.get("source-id") == OLD_VIDEO_URL


@pytest.mark.parametrize("body", [
    pytest.param(b'{"MediaSources": []}', id="empty-list"),
    pytest.param(b"{}", id="missing-list"),
    pytest.param(b'{"MediaSources": "oops"}', id="non-list"),
    pytest.param(b'{"MediaSources": ["text"]}', id="non-dict-source"),
    pytest.param(b'{"MediaSources": [{"Id": "other-id", "Path": "https://media.example/other.mkv"}]}', id="other-source"),
    pytest.param(b'{"MediaSources": [{"Path": "https://media.example/no-id.mkv"}]}', id="missing-id"),
])
@pytest.mark.parametrize("modify", [True, False])
def test_playback_pipeline_absent_media_source_keeps_mappings(body, modify) -> None:
    pipeline = PlaybackPipeline(body)
    pipeline.service.media_source_cache.remember("source-id", OLD_VIDEO_URL)

    pipeline.playback(pipeline.request(), modify=modify)

    assert pipeline.service.media_source_cache.get("source-id") == OLD_VIDEO_URL


def test_playback_pipeline_missing_path_clears_only_that_media_source_id() -> None:
    body = json.dumps({"MediaSources": [
        {"Id": "source-a"},
        {"Id": "source-b", "Path": "https://media.example/b.mkv"},
    ]}).encode("utf-8")
    pipeline = PlaybackPipeline(body)
    pipeline.service.media_source_cache.remember("source-a", OLD_VIDEO_URL)
    pipeline.service.media_source_cache.remember("source-b", "https://media.example/stale-b.mkv")

    pipeline.playback(pipeline.request(), modify=False)

    assert pipeline.service.media_source_cache.get("source-a") is None
    assert pipeline.service.media_source_cache.get("source-b") == "https://media.example/b.mkv"


def test_create_app_forwards_playback_and_emby_playback_to_upstream_each_time() -> None:
    """The real application assembly must not keep a response cache."""

    class TransactionClient:
        def __init__(self, **kwargs) -> None:
            self.calls: list[httpx.Request] = []

        async def forward(self, request: Request) -> httpx.Response:
            self.calls.append(request)
            transaction = len(self.calls)
            return httpx.Response(
                200,
                json={
                    "transaction": transaction,
                    "MediaSources": [{
                        "Id": f"source-{transaction}",
                        "Path": f"https://media.example/{transaction}.mkv",
                    }],
                },
                headers={"content-type": "application/json"},
            )

        async def close(self) -> None:
            pass

    settings = replace(Settings.from_env(), log_file="", access_log_file="")
    with patch.object(main_module, "JellyfinHttpClient", TransactionClient):
        app = main_module.create_app(settings)
        with TestClient(app) as client:
            dispatcher = app.state.dispatcher
            assert not hasattr(dispatcher, "_playback_info_cache")
            assert not hasattr(dispatcher._playback, "_cache")

            compact = client.post(
                "/Items/c7abcb3401d22d5cd3fd058cc914bdcf/PlaybackInfo",
                json={"DeviceProfile": {"Name": "Android"}},
            )
            hyphenated = client.get(
                "/emby/Items/c7abcb34-01d2-2d5c-d3fd-058cc914bdcf/PlaybackInfo",
                params={"UserId": "user-id"},
            )

    upstream = dispatcher._playback._http_client.calls  # type: ignore[attr-defined]
    assert len(upstream) == 2
    assert upstream[0].method == "POST"
    assert upstream[0].url.path == "/Items/c7abcb3401d22d5cd3fd058cc914bdcf/PlaybackInfo"
    assert upstream[1].method == "GET"
    assert upstream[1].url.path == "/emby/Items/c7abcb34-01d2-2d5c-d3fd-058cc914bdcf/PlaybackInfo"
    assert upstream[1].url.query == "UserId=user-id"

    assert compact.status_code == 200
    assert hyphenated.status_code == 200
    assert json.loads(compact.content)["transaction"] == 1
    assert json.loads(hyphenated.content)["transaction"] == 2
    for response in (compact, hyphenated):
        assert "x-jellyfinproxy-cache" not in response.headers
        assert response.headers["x-jellyfinproxy-version"]
        assert response.headers["x-request-id"]


def _app_with_fake_upstream(handler, **settings_overrides) -> tuple[object, object]:
    """Build the real app with a stub HTTP client class supplied by the test."""

    class MediaStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"media-"
            yield b"bytes"

    class StubClient:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs
            self.calls: list[httpx.Request] = []
            self.stream_calls: list[httpx.Request] = []

        async def forward(self, request: Request) -> httpx.Response:
            self.calls.append(request)
            return handler(request, len(self.calls))

        async def forward_stream(self, request: Request) -> httpx.Response:
            self.stream_calls.append(request)
            return httpx.Response(
                206,
                headers={"content-range": "bytes 0-8/100", "content-length": "11"},
                stream=MediaStream(),
            )

        async def close(self) -> None:
            pass

    settings = replace(
        Settings.from_env(),
        log_file="",
        access_log_file="",
        **settings_overrides,
    )
    patcher = patch.object(main_module, "JellyfinHttpClient", StubClient)
    patcher.start()
    return main_module.create_app(settings), patcher


class ScriptedAsyncStream(httpx.AsyncByteStream):
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.closed = False

    async def __aiter__(self):
        for offset in range(0, len(self.body), 8):
            yield self.body[offset:offset + 8]

    async def aclose(self) -> None:
        self.closed = True


def _app_with_scripted_upstream(responder, **settings_overrides):
    """Build the real app with a stub client that returns scripted responses.

    ``responder(request, transaction, *, stream)`` returns
    ``(status, headers, body)``. Streaming responses receive an observable
    async stream so tests can check that the proxy releases upstream bodies.
    """

    class StubClient:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs
            self.calls: list[httpx.Request] = []
            self.stream_calls: list[httpx.Request] = []
            self.streams: list[ScriptedAsyncStream] = []

        async def forward(self, request: Request) -> httpx.Response:
            self.calls.append(request)
            status, headers, body = responder(request, len(self.calls), stream=False)
            return httpx.Response(status, headers=headers, content=body)

        async def forward_stream(self, request: Request) -> httpx.Response:
            self.stream_calls.append(request)
            status, headers, body = responder(request, len(self.stream_calls), stream=True)
            stream = ScriptedAsyncStream(body)
            self.streams.append(stream)
            return httpx.Response(status, headers=headers, stream=stream)

        async def close(self) -> None:
            pass

    settings = replace(
        Settings.from_env(),
        log_file="",
        access_log_file="",
        **settings_overrides,
    )
    patcher = patch.object(main_module, "JellyfinHttpClient", StubClient)
    patcher.start()
    return main_module.create_app(settings), patcher


def _seed_media_mapping(request: Request) -> tuple[int, dict[str, str], bytes] | None:
    if not request.url.path.endswith("/PlaybackInfo"):
        return None
    return (
        200,
        {"content-type": "application/json"},
        json.dumps({
            "MediaSources": [{
                "Id": "source-id",
                "Path": "https://media.example/source.mkv",
            }],
        }).encode(),
    )


def test_create_app_issues_one_upstream_call_per_concurrent_request() -> None:
    rejected: list[str] = []

    def upstream(request: Request, transaction: int) -> httpx.Response:
        if transaction == 1:
            return httpx.Response(
                200,
                json={
                    "transaction": transaction,
                    "MediaSources": [{
                        "Id": "source-id",
                        "Path": f"https://media.example/{transaction}.mkv",
                    }],
                },
            )
        # The first response must never be reused for the remaining requests.
        rejected.append(str(transaction))
        return httpx.Response(503, json={"error": "no reuse"})

    app, patcher = _app_with_fake_upstream(upstream)

    async def scenario() -> list[httpx.Response]:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://proxy"
            ) as client:
                return await asyncio.gather(*[
                    client.post(
                        "/Items/abcdef0123456789abcdef0123456789/PlaybackInfo",
                        json={"DeviceProfile": {"Name": f"Device{index}"}},
                        headers={"X-Emby-Device-Id": f"device-{index}"},
                    )
                    for index in range(4)
                ])

    try:
        responses = asyncio.run(scenario())
    finally:
        patcher.stop()

    upstream_client = app.state.dispatcher._playback._http_client  # type: ignore[attr-defined]
    assert len(upstream_client.calls) == 4
    devices = sorted(call.headers["x-emby-device-id"] for call in upstream_client.calls)
    assert devices == [f"device-{index}" for index in range(4)]
    assert [response.status_code for response in responses] == [200, 503, 503, 503]
    successful = [
        json.loads(response.content)["transaction"]
        for response in responses
        if response.status_code == 200
    ]
    assert successful == [1]
    assert rejected == ["2", "3", "4"]
    for response in responses:
        assert "x-jellyfinproxy-cache" not in response.headers


def test_create_app_bypass_forwards_original_body_and_fills_video_redirect() -> None:
    original = b'{ "MediaSources": [{"Id":"source-id", "Path":"https://media.example/movie.mkv", "Protocol":"Http", "SupportsTranscoding":true}] }'
    state = {"status": 200, "body": original}

    def upstream(request: Request, transaction: int) -> httpx.Response:
        del request, transaction
        return httpx.Response(
            state["status"],
            content=state["body"],
            headers={"content-type": "application/json", "x-jellyfinproxy-cache": "MISS"},
        )

    app, patcher = _app_with_fake_upstream(upstream)
    try:
        with TestClient(app) as client:
            app.state.dispatcher._client_policy = ClientPolicy(
                (),
                playback_bypass_clients=("BypassClient",),
                video_bypass_clients=("VideoBypassClient",),
            )
            headers = {"x-emby-client": "BypassClient"}
            bypassed = client.post("/Items/item-id/PlaybackInfo", headers=headers)
            # The bypass response body is the upstream bytes, not a re-serialization.
            assert bypassed.content == original
            # An upstream header is still forwarded by the existing adapter.
            assert bypassed.headers["x-jellyfinproxy-cache"] == "MISS"

            redirect = client.get(
                "/Videos/item-id/stream.mkv",
                params={"mediaSourceId": "source-id"},
                follow_redirects=False,
            )
            assert redirect.status_code == 302
            assert redirect.headers["location"] == "https://media.example/movie.mkv"

            # A Video-bypassed client still streams through the transparent proxy.
            streamed = client.get(
                "/Videos/item-id/stream.mkv",
                params={"mediaSourceId": "source-id"},
                headers={"x-emby-client": "VideoBypassClient"},
            )
            assert streamed.status_code == 206
            assert streamed.content == b"media-bytes"
            assert streamed.headers["content-range"] == "bytes 0-8/100"
            assert "location" not in streamed.headers

            # A client without the bypass gets the modified document instead.
            # The default assembly changes no field: Jellyfin's values survive.
            modified = client.post("/Items/item-id/PlaybackInfo")
            document = json.loads(modified.content)
            assert document["MediaSources"][0]["Protocol"] == "Http"
            assert document["MediaSources"][0]["SupportsTranscoding"] is True

            # An upstream failure surfaces as-is; no earlier success is replayed.
            state.update(status=401, body=b'{"error":"denied"}')
            failed = client.post("/Items/item-id/PlaybackInfo")
            assert failed.status_code == 401
            assert failed.content == b'{"error":"denied"}'

            state.update(status=200, body=original)
            recovered = client.post("/Items/item-id/PlaybackInfo")
            assert recovered.status_code == 200
            assert json.loads(recovered.content)["MediaSources"][0]["Id"] == "source-id"
    finally:
        patcher.stop()

    upstream_client = app.state.dispatcher._playback._http_client  # type: ignore[attr-defined]
    assert len(upstream_client.calls) == 4
    assert [call.url.path for call in upstream_client.stream_calls] == [
        "/Videos/item-id/stream.mkv"
    ]


@pytest.mark.parametrize(("path", "status", "content_type", "body"), [
    pytest.param(
        "/api/danmu/source-id/raw",
        200,
        "application/xml; charset=utf-8",
        b"<danmu><message>first</message></danmu>",
        id="danmu-raw-xml",
    ),
    pytest.param(
        "/emby/api/danmu/source-id/raw",
        200,
        "application/xml; charset=utf-8",
        b"<danmu><message>first</message></danmu>",
        id="emby-danmu-raw-xml",
    ),
    pytest.param(
        "/api/danmu/source-id/raw",
        404,
        "text/plain; charset=utf-8",
        b"unknown danmu item",
        id="danmu-raw-404",
    ),
    pytest.param(
        "/emby/api/danmu/source-id/raw",
        404,
        "text/plain; charset=utf-8",
        b"unknown danmu item",
        id="emby-danmu-raw-404",
    ),
])
def test_create_app_danmu_raw_uses_plain_proxy_with_valid_media_mapping(
    path, status, content_type, body
) -> None:
    def responder(request: Request, transaction: int, *, stream: bool):
        seed = _seed_media_mapping(request)
        if seed is not None:
            return seed
        assert stream, f"raw entry must be streamed through the proxy, not fetched as {request.method}"
        return status, {"content-type": content_type, "x-upstream-danmu": "kept"}, body

    app, patcher = _app_with_scripted_upstream(responder)
    try:
        with TestClient(app) as client:
            seeded = client.post("/Items/source-id/PlaybackInfo")
            assert seeded.status_code == 200

            cache = app.state.dispatcher._video._media_source_cache  # type: ignore[attr-defined]
            with patch.object(cache, "get", wraps=cache.get) as cache_get:
                response = client.get(path, follow_redirects=False)
            assert cache_get.call_count == 0

            video = client.get("/Videos/source-id/stream.mkv", follow_redirects=False)
    finally:
        patcher.stop()

    upstream = app.state.dispatcher._proxy._http_client  # type: ignore[attr-defined]
    assert len(upstream.calls) == 1
    assert len(upstream.stream_calls) == 1
    assert upstream.stream_calls[0].url.path == path
    assert response.status_code == status
    assert response.content == body
    assert response.headers["content-type"] == content_type
    assert response.headers["x-upstream-danmu"] == "kept"
    assert "location" not in response.headers

    assert video.status_code == 302
    assert video.headers["location"] == "https://media.example/source.mkv"
    assert len(upstream.stream_calls) == 1


@pytest.mark.parametrize(("path", "query"), [
    pytest.param(
        "/api/danmu/source-id/raw/?MediaSourceId=source-id",
        "MediaSourceId=source-id",
        id="danmu-raw-trailing-slash",
    ),
    pytest.param(
        "/emby/api/danmu/source-id/raw?mediaSourceId=source-id",
        "mediaSourceId=source-id",
        id="emby-danmu-raw-lower-query",
    ),
    pytest.param(
        "/api/danmu/source-id/raw?MediaSourceId=source-id&mediaSourceId=other-id",
        "MediaSourceId=source-id&mediaSourceId=other-id",
        id="danmu-raw-two-query-names",
    ),
])
def test_create_app_danmu_raw_media_source_query_does_not_restore_redirect(path, query) -> None:
    def responder(request: Request, transaction: int, *, stream: bool):
        seed = _seed_media_mapping(request)
        if seed is not None:
            return seed
        assert stream
        return 404, {"content-type": "text/plain"}, b"upstream raw response"

    app, patcher = _app_with_scripted_upstream(responder)
    try:
        with TestClient(app) as client:
            assert client.post("/Items/source-id/PlaybackInfo").status_code == 200
            response = client.get(path, follow_redirects=False)
    finally:
        patcher.stop()

    upstream = app.state.dispatcher._proxy._http_client  # type: ignore[attr-defined]
    assert len(upstream.stream_calls) == 1
    assert upstream.stream_calls[0].url.path == path.split("?", 1)[0]
    assert upstream.stream_calls[0].url.query == query
    assert response.status_code == 404
    assert response.content == b"upstream raw response"
    assert "location" not in response.headers


@pytest.mark.parametrize(("status", "headers", "body"), [
    pytest.param(401, {"content-type": "text/plain", "www-authenticate": 'Basic realm="jellyfin"'}, b"unauthorized", id="401"),
    pytest.param(403, {"content-type": "text/plain"}, b"forbidden", id="403"),
    pytest.param(500, {"content-type": "text/plain"}, b"upstream failure", id="500"),
    pytest.param(
        302,
        {"content-type": "text/plain", "location": "https://jellyfin.example/upstream-redirect"},
        b"redirecting",
        id="upstream-302",
    ),
])
def test_create_app_danmu_raw_preserves_upstream_status_and_headers(status, headers, body) -> None:
    def responder(request: Request, transaction: int, *, stream: bool):
        seed = _seed_media_mapping(request)
        if seed is not None:
            return seed
        assert stream
        return status, headers, body

    app, patcher = _app_with_scripted_upstream(responder)
    try:
        with TestClient(app) as client:
            assert client.post("/Items/source-id/PlaybackInfo").status_code == 200
            response = client.get("/emby/api/danmu/source-id/raw", follow_redirects=False)
    finally:
        patcher.stop()

    upstream = app.state.dispatcher._proxy._http_client  # type: ignore[attr-defined]
    assert len(upstream.stream_calls) == 1
    assert response.status_code == status
    assert response.content == body
    for name, value in headers.items():
        assert response.headers[name] == value
    if status == 302:
        assert response.headers["location"] == "https://jellyfin.example/upstream-redirect"
    else:
        assert "location" not in response.headers


def test_create_app_danmu_raw_head_forwards_headers_without_body() -> None:
    def responder(request: Request, transaction: int, *, stream: bool):
        seed = _seed_media_mapping(request)
        if seed is not None:
            return seed
        assert stream
        assert request.method == "HEAD"
        return 200, {"content-type": "application/xml", "content-length": "0"}, b""

    app, patcher = _app_with_scripted_upstream(responder)
    try:
        with TestClient(app) as client:
            assert client.post("/Items/source-id/PlaybackInfo").status_code == 200
            response = client.head("/api/danmu/source-id/raw", follow_redirects=False)
    finally:
        patcher.stop()

    upstream = app.state.dispatcher._proxy._http_client  # type: ignore[attr-defined]
    assert len(upstream.stream_calls) == 1
    assert response.status_code == 200
    assert response.content == b""
    assert response.headers["content-type"] == "application/xml"
    assert "location" not in response.headers
    assert upstream.streams[0].closed


@pytest.mark.parametrize("client_name", ["SenPlayer", "VideoBypassClient", "GlobalBypassClient"])
def test_create_app_danmu_raw_forwards_range_auth_and_ignores_bypass_lists(client_name) -> None:
    token = "danmu-auth-sentinel-value"

    def responder(request: Request, transaction: int, *, stream: bool):
        seed = _seed_media_mapping(request)
        if seed is not None:
            return seed
        assert stream
        return 206, {
            "content-type": "video/mp4",
            "content-range": "bytes 0-3/100",
            "accept-ranges": "bytes",
        }, b"data"

    app, patcher = _app_with_scripted_upstream(
        responder,
        bypass_clients=("GlobalBypassClient",),
        video_bypass_clients=("VideoBypassClient",),
    )
    try:
        with TestClient(app) as client:
            assert client.post("/Items/source-id/PlaybackInfo").status_code == 200
            response = client.get(
                "/api/danmu/source-id/raw?MediaSourceId=source-id&api_key=secret%2Bvalue",
                headers={
                    "x-emby-client": client_name,
                    "range": "bytes=0-3",
                    "authorization": f'MediaBrowser Client="x", Token={token}',
                },
                follow_redirects=False,
            )
    finally:
        patcher.stop()

    upstream = app.state.dispatcher._proxy._http_client  # type: ignore[attr-defined]
    assert len(upstream.stream_calls) == 1
    forwarded = upstream.stream_calls[0]
    assert forwarded.url.path == "/api/danmu/source-id/raw"
    assert forwarded.url.query == "MediaSourceId=source-id&api_key=secret%2Bvalue"
    assert forwarded.headers["range"] == "bytes=0-3"
    assert forwarded.headers["authorization"] == f'MediaBrowser Client="x", Token={token}'
    assert response.status_code == 206
    assert response.content == b"data"
    assert response.headers["content-range"] == "bytes 0-3/100"
    assert "location" not in response.headers


def test_create_app_danmu_raw_forwards_percent_encoded_path_and_query() -> None:
    path = "/api/danmu/source%20id/raw"
    query = "MediaSourceId=source%2Did&api_key=secret%2Bvalue"

    def responder(request: Request, transaction: int, *, stream: bool):
        seed = _seed_media_mapping(request)
        if seed is not None:
            return seed
        assert stream
        return 404, {"content-type": "text/plain"}, b"encoded raw"

    app, patcher = _app_with_scripted_upstream(responder)
    try:
        with TestClient(app) as client:
            assert client.post("/Items/source-id/PlaybackInfo").status_code == 200
            response = client.get(f"{path}?{query}", follow_redirects=False)
    finally:
        patcher.stop()

    upstream = app.state.dispatcher._proxy._http_client  # type: ignore[attr-defined]
    assert len(upstream.stream_calls) == 1
    forwarded = upstream.stream_calls[0]
    assert forwarded.scope["raw_path"].decode("latin-1") == path
    assert forwarded.scope["query_string"].decode("latin-1") == query
    assert response.status_code == 404
    assert response.content == b"encoded raw"
    assert "location" not in response.headers


def test_create_app_playback_upstream_error_is_not_replayed_from_success() -> None:
    calls = {"n": 0}

    def upstream(request: Request, transaction: int) -> httpx.Response:
        del request, transaction
        calls["n"] += 1
        if calls["n"] == 2:
            raise httpx.ConnectError("upstream unreachable")
        if calls["n"] == 3:
            return httpx.Response(200, content=b"not-json", headers={"content-type": "text/plain"})
        return httpx.Response(
            200,
            json={
                "transaction": calls["n"],
                "MediaSources": [{
                    "Id": "source-id",
                    "Path": "https://media.example/movie.mkv",
                }],
            },
        )

    app, patcher = _app_with_fake_upstream(upstream)
    try:
        with TestClient(app) as client:
            first = client.post("/Items/item-id/PlaybackInfo")
            assert first.status_code == 200

            with pytest.raises(httpx.ConnectError):
                client.post("/Items/item-id/PlaybackInfo")

            broken = client.post("/Items/item-id/PlaybackInfo")
            assert broken.status_code == 200
            assert broken.content == b"not-json"

            recovered = client.post("/Items/item-id/PlaybackInfo")
            assert json.loads(recovered.content)["transaction"] == 4
    finally:
        patcher.stop()

    upstream_client = app.state.dispatcher._playback._http_client  # type: ignore[attr-defined]
    assert len(upstream_client.calls) == 4


def test_routes_cover_playback_and_video_variants() -> None:
    router = Router()
    assert router.match("/Items/abc/PlaybackInfo", "GET") is HandlerType.PLAYBACK
    assert router.match("/emby/Items/abc/PlaybackInfo", "GET") is HandlerType.PLAYBACK
    assert router.match("/Items/abc/PlaybackInfo", "POST") is HandlerType.PLAYBACK
    assert router.match("/Items/abc/PlaybackInfo", "PUT") is HandlerType.DEFAULT
    for path in (
        "/Videos/id/stream",
        "/Videos/id/stream.mp4",
        "/Videos/id/master.m3u8",
        "/Videos/id/hls/a.ts",
        "/videos/788be25df9307eb419a2316de9f9d699/stream.mkv",
        "/video",
        "/video/stream/movie.mkv",
    ):
        assert router.match(path, "GET") is HandlerType.VIDEO
    assert router.match("/Video/stream/movie.mkv", "GET") is HandlerType.DEFAULT
    assert router.match("/videography", "GET") is HandlerType.DEFAULT


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
@pytest.mark.parametrize("path", [
    "/emby/api/danmu/source-id/raw",
    "/emby/api/danmu/source-id/raw/",
    "/api/danmu/source-id/raw",
    "/api/danmu/source-id/raw/",
])
def test_router_keeps_danmu_raw_out_of_video_routing(path, method) -> None:
    assert Router().match(path, method) is HandlerType.DEFAULT


@pytest.mark.parametrize("query_string", [
    b"MediaSourceId=source-id",
    b"mediaSourceId=source-id",
    b"MediaSourceId=source-id&mediaSourceId=other-id",
    b"MediaSourceId=&mediaSourceId=source-id",
])
def test_video_handler_redirects_to_cached_media_source_path(query_string: bytes) -> None:
    class FailingProxy:
        async def handle(self, request: Request) -> Response:
            raise AssertionError(f"unexpected proxy fallback for {request.url.path}")

    cache = MediaSourceCache()
    cache.remember("source-id", "https://media.example/movie.mkv?token=secret")
    request = Request({
        "type": "http",
        "method": "GET",
        "scheme": "http",
        "server": ("proxy", 8097),
        "path": "/videos/item/stream.mkv",
        "query_string": query_string,
        "headers": [],
    })

    response = asyncio.run(VideoHandler(FailingProxy(), cache).handle(request))  # type: ignore[arg-type]

    assert response.status_code == 302
    assert response.headers["location"] == "https://media.example/movie.mkv?token=secret"


def test_video_handler_uses_hyphenated_path_id_when_query_id_is_missing() -> None:
    class FailingProxy:
        async def handle(self, request: Request) -> Response:
            raise AssertionError(f"unexpected proxy fallback for {request.url.path}")

    cache = MediaSourceCache()
    cache.remember(
        "788be25df9307eb419a2316de9f9d699",
        "https://media.example/movie.mkv",
    )
    request = Request({
        "type": "http",
        "method": "GET",
        "scheme": "http",
        "server": ("proxy", 8097),
        "path": "/Videos/788be25d-f930-7eb4-19a2-316de9f9d699/stream",
        "query_string": b"",
        "headers": [],
    })

    response = asyncio.run(VideoHandler(FailingProxy(), cache).handle(request))  # type: ignore[arg-type]

    assert response.status_code == 302
    assert response.headers["location"] == "https://media.example/movie.mkv"


def test_playback_service_caches_modified_media_source_path() -> None:
    cache = MediaSourceCache()
    document = {"MediaSources": [{
        "Id": "source-id",
        "Path": "https://media.example/movie.mkv",
    }]}

    asyncio.run(
        PlaybackService(
            MediaSourceService(MediaResolver(), rules=(ProtocolFileRule(),)),
            cache,
        ).modify(document)
    )

    assert cache.get("source-id") == "https://media.example/movie.mkv"


def test_media_source_cache_rejects_local_paths() -> None:
    cache = MediaSourceCache()
    cache.remember("source-id", "/media/movie.mkv")
    assert cache.get("source-id") is None


def test_media_source_cache_normalizes_uuid_format() -> None:
    cache = MediaSourceCache()
    cache.remember(
        "788be25df9307eb419a2316de9f9d699",
        "https://media.example/movie.mkv",
    )
    assert (
        cache.get("788BE25D-F930-7EB4-19A2-316DE9F9D699")
        == "https://media.example/movie.mkv"
    )


OLD_URL = "https://media.example/old.mkv"
NEW_URL = "https://media.example/new.mkv?token=new"
INVALID_PATH_CASES = [
    pytest.param("/media/movie.mkv", id="local-path"),
    pytest.param("", id="empty-string"),
    pytest.param(None, id="none"),
    pytest.param(1234, id="integer"),
    pytest.param("ftp://media.example/movie.mkv", id="ftp-scheme"),
    pytest.param("file:///media/movie.mkv", id="file-scheme"),
    pytest.param("https:///movie.mkv", id="missing-netloc"),
    pytest.param("http://", id="scheme-only"),
]


@pytest.mark.parametrize("path", ["https://media.example/movie.mkv", "http://media.example/movie.mkv"])
def test_media_source_cache_stores_valid_http_urls(path) -> None:
    cache = MediaSourceCache()
    cache.remember("source-id", path)
    assert cache.get("source-id") == path


def test_media_source_cache_accepts_uppercase_scheme() -> None:
    cache = MediaSourceCache()
    cache.remember("source-id", "HTTPS://media.example/movie.mkv")
    assert cache.get("source-id") == "HTTPS://media.example/movie.mkv"


def test_media_source_cache_overwrites_same_media_source_id() -> None:
    cache = MediaSourceCache()
    cache.remember("source-id", OLD_URL)
    cache.remember("source-id", NEW_URL)
    assert cache.get("source-id") == NEW_URL


@pytest.mark.parametrize("path", INVALID_PATH_CASES)
def test_media_source_cache_clears_existing_mapping_for_invalid_path(path) -> None:
    cache = MediaSourceCache()
    cache.remember("source-id", OLD_URL)
    cache.remember("source-id", path)
    assert cache.get("source-id") is None


@pytest.mark.parametrize("path", INVALID_PATH_CASES)
def test_media_source_cache_invalid_path_only_clears_that_media_source_id(path) -> None:
    cache = MediaSourceCache()
    cache.remember("source-a", OLD_URL)
    cache.remember("source-b", "https://media.example/other.mkv")
    cache.remember("source-a", path)
    assert cache.get("source-a") is None
    assert cache.get("source-b") == "https://media.example/other.mkv"


@pytest.mark.parametrize("path", ["http://[invalid", "https://[::1", "http://[::1]x"])
def test_media_source_cache_clears_existing_mapping_for_unparsable_path(path) -> None:
    cache = MediaSourceCache()
    cache.remember("source-id", OLD_URL)
    cache.remember("source-id", path)
    assert cache.get("source-id") is None


def test_media_source_cache_unparsable_path_keeps_other_media_source_id() -> None:
    cache = MediaSourceCache()
    cache.remember("source-a", OLD_URL)
    cache.remember("source-b", "https://media.example/other.mkv")
    cache.remember("source-a", "http://[invalid")
    assert cache.get("source-a") is None
    assert cache.get("source-b") == "https://media.example/other.mkv"


def test_media_source_cache_repeated_invalid_path_is_idempotent() -> None:
    cache = MediaSourceCache()
    cache.remember("source-id", "/media/movie.mkv")
    cache.remember("source-id", None)
    cache.remember("source-id", "http://[invalid")
    assert cache.get("source-id") is None


@pytest.mark.parametrize("media_source_id", [None, "", 42, b"source-id"])
def test_media_source_cache_ignores_invalid_media_source_id(media_source_id) -> None:
    cache = MediaSourceCache()
    cache.remember("source-id", OLD_URL)
    cache.remember(media_source_id, "/media/movie.mkv")
    cache.remember(media_source_id, None)
    assert cache.get("source-id") == OLD_URL


@pytest.mark.parametrize(
    ("stored_id", "cleared_id"),
    [
        pytest.param(
            "788be25df9307eb419a2316de9f9d699",
            "788BE25D-F930-7EB4-19A2-316DE9F9D699",
            id="compact-stored-hyphenated-cleared",
        ),
        pytest.param(
            "788BE25D-F930-7EB4-19A2-316DE9F9D699",
            "788be25df9307eb419a2316de9f9d699",
            id="hyphenated-stored-compact-cleared",
        ),
    ],
)
def test_media_source_cache_invalid_path_clears_normalized_uuid_key(stored_id, cleared_id) -> None:
    cache = MediaSourceCache()
    cache.remember(stored_id, OLD_URL)
    cache.remember(cleared_id, "/media/movie.mkv")
    assert cache.get(stored_id) is None
    assert cache.get(cleared_id) is None


def test_media_source_cache_keeps_case_sensitive_non_uuid_ids() -> None:
    cache = MediaSourceCache()
    cache.remember("Source-Id", OLD_URL)
    cache.remember("source-id", "/media/movie.mkv")
    assert cache.get("Source-Id") == OLD_URL
    assert cache.get("source-id") is None


def test_media_source_cache_remapping_after_invalid_path_restores_lookup() -> None:
    cache = MediaSourceCache()
    cache.remember("source-id", OLD_URL)
    cache.remember("source-id", None)
    assert cache.get("source-id") is None
    cache.remember("source-id", NEW_URL)
    assert cache.get("source-id") == NEW_URL


def test_media_source_cache_default_capacity_keeps_lru_behavior() -> None:
    cache = MediaSourceCache()
    cache.remember("source-id", OLD_URL)
    for index in range(4095):
        cache.remember(f"source-{index}", f"https://media.example/{index}.mkv")
    assert cache.get("source-0") == "https://media.example/0.mkv"
    cache.remember("source-4095", "https://media.example/4095.mkv")
    assert cache.get("source-id") is None
    assert cache.get("source-0") == "https://media.example/0.mkv"


def test_media_source_cache_capacity_handles_fill_plus_one() -> None:
    cache = MediaSourceCache(max_entries=2)
    cache.remember("source-a", OLD_URL)
    for index in range(2):
        cache.remember(f"source-{index}", f"https://media.example/{index}.mkv")
    assert cache.get("source-a") is None
    assert cache.get("source-0") == "https://media.example/0.mkv"
    assert cache.get("source-1") == "https://media.example/1.mkv"


def test_media_source_cache_clearing_one_entry_does_not_evict_others() -> None:
    cache = MediaSourceCache(max_entries=2)
    cache.remember("source-a", OLD_URL)
    cache.remember("source-b", "https://media.example/b.mkv")
    cache.remember("source-a", "/media/movie.mkv")
    assert cache.get("source-a") is None
    assert cache.get("source-b") == "https://media.example/b.mkv"
    cache.remember("source-c", "https://media.example/c.mkv")
    assert cache.get("source-b") == "https://media.example/b.mkv"
    assert cache.get("source-c") == "https://media.example/c.mkv"


def test_client_bypass_is_case_insensitive_across_headers() -> None:
    policy = ClientPolicy(("Infuse", "Kodi"))
    assert policy.should_bypass({"user-agent": "Infuse/8"})
    assert policy.should_bypass({"x-emby-client": "kodi"})
    assert not policy.should_bypass({"user-agent": "Jellyfin Web"})


def test_client_can_bypass_playback_and_video_independently() -> None:
    policy = ClientPolicy(
        ("Client D",),
        playback_bypass_clients=("Client B",),
        video_bypass_clients=("Client A",),
    )

    client_a = {"x-emby-client": "Client A"}
    assert not policy.should_bypass(client_a, HandlerType.PLAYBACK)
    assert policy.should_bypass(client_a, HandlerType.VIDEO)

    client_b = {"x-emby-client": "Client B"}
    assert policy.should_bypass(client_b, HandlerType.PLAYBACK)
    assert not policy.should_bypass(client_b, HandlerType.VIDEO)

    client_c = {"x-emby-client": "Client C"}
    assert not policy.should_bypass(client_c, HandlerType.PLAYBACK)
    assert not policy.should_bypass(client_c, HandlerType.VIDEO)

    client_d = {"x-emby-client": "Client D"}
    assert policy.should_bypass(client_d, HandlerType.PLAYBACK)
    assert policy.should_bypass(client_d, HandlerType.VIDEO)
    assert policy.should_bypass(client_d, HandlerType.DEFAULT)


def test_media_resolver_only_analyzes_existing_http_urls() -> None:
    resolver = MediaResolver()
    analyzed = resolver.analyze("https://alist.example.com/movie/test.mkv")
    assert analyzed is not None
    assert analyzed.scheme == "https"
    assert analyzed.host == "alist.example.com"
    assert resolver.analyze("/media/movie/test.strm") is None
    assert resolver.analyze("file:///media/movie/test.mkv") is None


def test_playback_passthrough_preserves_jellyfin_media_source() -> None:
    source = {
        "Path": "https://alist.example.com/movie/test.mkv",
        "Protocol": "Http",
        "EncoderProtocol": "Hls",
        "IsRemote": True,
        "SupportsDirectPlay": True,
        "SupportsDirectStream": False,
        "MediaStreams": [{"Codec": "hevc"}],
        "Bitrate": 123,
        "RunTimeTicks": 456,
        "Container": "mkv",
        "ETag": "etag-value",
        "Id": "source-id",
    }
    document = {"MediaSources": [source.copy()]}
    result = asyncio.run(
        PlaybackService(MediaSourceService(MediaResolver())).modify(document)
    )
    assert result["MediaSources"][0] == source


def test_playback_rewrite_changes_only_path() -> None:
    document = {
        "MediaSources": [{
            "Path": "https://alist.example.com/movie/test.mkv",
            "Protocol": "Http",
            "EncoderProtocol": "Hls",
            "IsRemote": True,
            "SupportsDirectPlay": True,
            "SupportsDirectStream": False,
            "MediaStreams": [{"Codec": "hevc"}],
            "Bitrate": 123,
            "RunTimeTicks": 456,
            "Container": "mkv",
            "ETag": "etag-value",
            "Id": "source-id",
        }]
    }
    service = MediaSourceService(MediaResolver(), rules=(RewriteRule(),))
    result = asyncio.run(PlaybackService(service).modify(document))
    source = result["MediaSources"][0]
    assert source["Path"] == "https://cdn.example.com/movie/test.mkv"
    assert source["Protocol"] == "Http"
    assert source["EncoderProtocol"] == "Hls"
    assert source["IsRemote"] is True
    assert source["SupportsDirectPlay"] is True
    assert source["SupportsDirectStream"] is False
    assert source["MediaStreams"] == [{"Codec": "hevc"}]
    assert source["Bitrate"] == 123
    assert source["RunTimeTicks"] == 456
    assert source["Container"] == "mkv"
    assert source["ETag"] == "etag-value"
    assert source["Id"] == "source-id"


def test_protocol_file_rule_disables_transcoding() -> None:
    source = {
        "Path": "https://alist.example.com/movie/test.mkv",
        "Protocol": "Http",
        "EncoderProtocol": "Hls",
        "SupportsDirectPlay": True,
        "SupportsDirectStream": False,
        "SupportsTranscoding": True,
        "MediaStreams": [{"Codec": "hevc"}],
    }
    document = {"MediaSources": [source.copy()]}
    service = MediaSourceService(MediaResolver(), rules=(ProtocolFileRule(),))
    result = asyncio.run(PlaybackService(service).modify(document))
    modified = result["MediaSources"][0]
    assert modified["Protocol"] == "File"
    assert modified["SupportsTranscoding"] is False
    assert modified["Path"] == source["Path"]
    assert modified["EncoderProtocol"] == source["EncoderProtocol"]
    assert modified["SupportsDirectPlay"] is True
    assert modified["SupportsDirectStream"] is False
    assert modified["MediaStreams"] == source["MediaStreams"]


def test_decoded_upstream_body_drops_stale_encoding_headers() -> None:
    upstream = httpx.Response(
        200,
        headers={
            "Content-Encoding": "gzip",
            "Content-Length": "100",
            "Date": "Mon, 03 Aug 2026 00:00:00 GMT",
            "Server": "Kestrel",
            "X-Test": "kept",
        },
        content=gzip.compress(b"decoded body"),
    )
    headers = response_headers(upstream)
    assert "content-encoding" not in headers
    assert "content-length" not in headers
    assert "date" not in headers
    assert "server" not in headers
    assert headers["x-test"] == "kept"


def test_streaming_headers_preserve_range_and_representation_metadata() -> None:
    upstream = httpx.Response(
        206,
        headers={
            "Content-Length": "4",
            "Content-Range": "bytes 0-3/100",
            "Accept-Ranges": "bytes",
            "Content-Encoding": "gzip",
            "Transfer-Encoding": "chunked",
            "Server": "Kestrel",
        },
    )

    headers = streaming_response_headers(upstream)

    assert headers["content-length"] == "4"
    assert headers["content-range"] == "bytes 0-3/100"
    assert headers["accept-ranges"] == "bytes"
    assert headers["content-encoding"] == "gzip"
    assert "transfer-encoding" not in headers
    assert "server" not in headers


def test_proxy_handler_streams_and_closes_upstream_response() -> None:
    class ChunkStream(httpx.AsyncByteStream):
        def __init__(self) -> None:
            self.closed = False

        async def __aiter__(self):
            yield b"ab"
            yield b"cd"

        async def aclose(self) -> None:
            self.closed = True

    stream = ChunkStream()
    upstream = httpx.Response(
        206,
        headers={"Content-Length": "4", "Content-Range": "bytes 0-3/100"},
        stream=stream,
    )

    class StreamingClient:
        async def forward_stream(self, request: Request) -> httpx.Response:
            assert request.headers["range"] == "bytes=0-3"
            return upstream

    request = Request({
        "type": "http",
        "method": "GET",
        "scheme": "http",
        "server": ("proxy", 8097),
        "path": "/videos/item/stream.mkv",
        "query_string": b"",
        "headers": [(b"range", b"bytes=0-3")],
    })

    async def consume() -> tuple[Response, bytes]:
        response = await ProxyHandler(StreamingClient()).handle(request)  # type: ignore[arg-type]
        assert not upstream.is_stream_consumed
        body = b"".join([chunk async for chunk in response.body_iterator])  # type: ignore[attr-defined]
        return response, body

    response, body = asyncio.run(consume())
    assert response.status_code == 206
    assert response.headers["content-range"] == "bytes 0-3/100"
    assert body == b"abcd"
    assert stream.closed


# --- PlaybackInfo field configuration -------------------------------------


REMOTE_SOURCE = {
    "Id": "source-id",
    "Path": "https://media.example/movie.mkv",
    "Protocol": "Http",
    "EncoderProtocol": "Hls",
    "SupportsDirectPlay": True,
    "SupportsTranscoding": True,
    "MediaStreams": [{"Codec": "hevc"}],
    "ETag": "etag-value",
}


def playback_service_with_fields(**overrides) -> PlaybackService:
    return PlaybackService(
        MediaSourceService(MediaResolver()),
        field_overrides=PlaybackFieldOverrides(**overrides),
    )


def test_default_playback_fields_change_nothing() -> None:
    document = {
        "ServerName": "Upstream",
        "MediaSources": [REMOTE_SOURCE.copy(), {"Id": "local-id", "Path": "/media/movie.mkv"}],
    }

    result = asyncio.run(PlaybackService(MediaSourceService(MediaResolver())).modify(document))

    assert result == {
        "ServerName": "Upstream",
        "MediaSources": [REMOTE_SOURCE, {"Id": "local-id", "Path": "/media/movie.mkv"}],
    }
    assert result["MediaSources"][0]["Protocol"] == "Http"
    assert result["MediaSources"][0]["SupportsTranscoding"] is True


def test_explicit_legacy_fields_restore_previous_default_rule() -> None:
    document = {"MediaSources": [REMOTE_SOURCE.copy()]}
    service = playback_service_with_fields(
        media_source_fields={"Protocol": "File", "SupportsTranscoding": False},
    )

    source = asyncio.run(service.modify(document))["MediaSources"][0]

    assert source["Protocol"] == "File"
    assert source["SupportsTranscoding"] is False
    assert source["Path"] == REMOTE_SOURCE["Path"]
    assert source["EncoderProtocol"] == "Hls"
    assert source["SupportsDirectPlay"] is True
    assert source["MediaStreams"] == [{"Codec": "hevc"}]
    assert source["ETag"] == "etag-value"
    assert source["Id"] == "source-id"


def test_single_field_override_does_not_trigger_other_fields() -> None:
    document = {"MediaSources": [REMOTE_SOURCE.copy()]}
    service = playback_service_with_fields(media_source_fields={"SupportsDirectPlay": False})

    source = asyncio.run(service.modify(document))["MediaSources"][0]

    assert source["SupportsDirectPlay"] is False
    assert source["Protocol"] == "Http"
    assert source["SupportsTranscoding"] is True


def test_root_field_override_scope_is_the_response_root_only() -> None:
    document = {
        "ServerName": "Upstream",
        "MediaSources": [REMOTE_SOURCE.copy()],
    }
    service = playback_service_with_fields(
        response_fields={"ServerName": "Proxy", "AddedRootField": [1, 2]},
    )

    result = asyncio.run(service.modify(document))

    assert result["ServerName"] == "Proxy"
    assert result["AddedRootField"] == [1, 2]
    # Root overrides never reach the media source objects.
    assert result["MediaSources"][0] == REMOTE_SOURCE


def test_media_source_fields_only_apply_to_usable_remote_sources() -> None:
    document = {"MediaSources": [
        REMOTE_SOURCE.copy(),
        {"Id": "local-id", "Path": "/media/movie.mkv", "Protocol": "File"},
        {"Id": "missing-path-id", "Protocol": "Http"},
        {"Id": "ftp-id", "Path": "ftp://media.example/movie.mkv"},
        "not-an-object",
    ]}
    service = playback_service_with_fields(
        media_source_fields={"Protocol": "File", "SupportsTranscoding": False},
    )

    sources = asyncio.run(service.modify(document))["MediaSources"]

    assert sources[0]["Protocol"] == "File"
    assert sources[0]["SupportsTranscoding"] is False
    assert sources[1] == {"Id": "local-id", "Path": "/media/movie.mkv", "Protocol": "File"}
    assert sources[2] == {"Id": "missing-path-id", "Protocol": "Http"}
    assert sources[3] == {"Id": "ftp-id", "Path": "ftp://media.example/movie.mkv"}
    assert sources[4] == "not-an-object"
    assert service.media_source_cache.get("local-id") is None
    assert service.media_source_cache.get("missing-path-id") is None


def test_complex_field_values_replace_whole_field_and_keep_types() -> None:
    document = {"MediaSources": [{
        "Id": "source-id",
        "Path": "https://media.example/movie.mkv",
        "MediaStreams": [{"Codec": "hevc"}, {"Codec": "aac"}],
        "Tags": ["upstream"],
    }]}
    service = playback_service_with_fields(media_source_fields={
        "MediaStreams": [{"Codec": "h264"}],
        "Tags": ["proxy", "field"],
        "SupportsDirectPlay": "false",
        "Fraction": 1.5,
        "Whole": 7,
    })

    source = asyncio.run(service.modify(document))["MediaSources"][0]

    # Arrays and objects are replaced wholesale, not merged.
    assert source["MediaStreams"] == [{"Codec": "h264"}]
    assert source["Tags"] == ["proxy", "field"]
    # Values keep their configured TOML type instead of following the field name.
    assert source["SupportsDirectPlay"] == "false"
    assert source["Fraction"] == 1.5
    assert source["Whole"] == 7


def test_configured_rule_extension_still_runs_without_implicit_rule() -> None:
    document = {"MediaSources": [{
        **REMOTE_SOURCE,
        "Path": "https://alist.example.com/movie/test.mkv",
    }]}
    service = PlaybackService(
        MediaSourceService(MediaResolver(), rules=(RewriteRule(),)),
        field_overrides=PlaybackFieldOverrides(),
    )

    source = asyncio.run(service.modify(document))["MediaSources"][0]

    assert source["Path"] == "https://cdn.example.com/movie/test.mkv"
    assert source["Protocol"] == "Http"


def test_explicit_media_source_fields_win_over_policy_rule_values() -> None:
    document = {"MediaSources": [REMOTE_SOURCE.copy()]}
    service = PlaybackService(
        MediaSourceService(MediaResolver(), rules=(ProtocolFileRule(),)),
        field_overrides=PlaybackFieldOverrides(
            media_source_fields={"Protocol": "Http", "SupportsDirectPlay": False},
        ),
    )

    source = asyncio.run(service.modify(document))["MediaSources"][0]

    # The policy rule ran (it set SupportsTranscoding), then the explicit value won.
    assert source["Protocol"] == "Http"
    assert source["SupportsDirectPlay"] is False
    assert source["SupportsTranscoding"] is False


def test_mutable_field_values_are_isolated_per_source_and_per_request() -> None:
    template = {"MediaSources": [
        {"Id": "source-a", "Path": "https://media.example/a.mkv"},
        {"Id": "source-b", "Path": "https://media.example/b.mkv"},
    ]}
    service = playback_service_with_fields(
        media_source_fields={"Tags": ["shared"], "Details": {"nested": [1]}},
    )

    first = asyncio.run(service.modify(json.loads(json.dumps(template))))
    first_sources = first["MediaSources"]
    first_sources[0]["Tags"].append("mutated-a")
    first_sources[0]["Details"]["nested"].append(2)

    assert first_sources[1]["Tags"] == ["shared"]
    assert first_sources[1]["Details"] == {"nested": [1]}

    second = asyncio.run(service.modify(json.loads(json.dumps(template))))
    assert second["MediaSources"][0]["Tags"] == ["shared"]
    assert second["MediaSources"][0]["Details"] == {"nested": [1]}


def test_overridden_media_source_id_drives_video_redirect_and_clears_old_id() -> None:
    cache = MediaSourceCache()
    cache.remember("source-id", "https://media.example/stale.mkv")
    cache.remember("other-id", "https://media.example/other.mkv")
    service = PlaybackService(
        MediaSourceService(MediaResolver()),
        cache,
        PlaybackFieldOverrides(media_source_fields={"Id": "new-source-id"}),
    )
    document = {"MediaSources": [REMOTE_SOURCE.copy()]}

    source = asyncio.run(service.modify(document))["MediaSources"][0]

    assert source["Id"] == "new-source-id"
    assert cache.get("source-id") is None
    assert cache.get("new-source-id") == REMOTE_SOURCE["Path"]
    assert cache.get("other-id") == "https://media.example/other.mkv"

    class UnexpectedProxy:
        async def handle(self, request: Request) -> Response:
            pytest.fail("Video should redirect through the final media source Id")

    redirect = asyncio.run(VideoHandler(UnexpectedProxy(), cache).handle(  # type: ignore[arg-type]
        Request({
            "type": "http", "method": "GET", "scheme": "http",
            "server": ("proxy", 8097), "path": "/Videos/new-source-id/stream.mkv",
            "query_string": b"", "headers": [],
        }),
    ))
    assert redirect.status_code == 302
    assert redirect.headers["location"] == REMOTE_SOURCE["Path"]


def test_overridden_invalid_path_clears_only_the_matching_mapping() -> None:
    cache = MediaSourceCache()
    cache.remember("source-id", "https://media.example/stale.mkv")
    cache.remember("other-id", "https://media.example/other.mkv")
    service = PlaybackService(
        MediaSourceService(MediaResolver()),
        cache,
        PlaybackFieldOverrides(media_source_fields={"Path": "/media/local.mkv"}),
    )

    source = asyncio.run(service.modify({"MediaSources": [REMOTE_SOURCE.copy()]}))["MediaSources"][0]

    assert source["Path"] == "/media/local.mkv"
    assert cache.get("source-id") is None
    assert cache.get("other-id") == "https://media.example/other.mkv"


@pytest.mark.parametrize("document", [
    pytest.param([{"ServerName": "Upstream"}], id="non-object-root"),
    pytest.param({"ServerName": "Upstream"}, id="missing-media-sources"),
    pytest.param({"MediaSources": "oops"}, id="non-list-media-sources"),
    pytest.param({"MediaSources": {"Id": "source-id"}}, id="non-list-media-source-object"),
])
def test_field_overrides_tolerate_unexpected_document_shapes(document) -> None:
    service = playback_service_with_fields(
        response_fields={"ServerName": "Proxy"},
        media_source_fields={"Protocol": "File"},
    )

    result = asyncio.run(service.modify(document))

    if isinstance(document, list):
        assert result == document
    else:
        assert result["ServerName"] == "Proxy"
        # No MediaSources list is created or converted.
        assert result.get("MediaSources") == document.get("MediaSources")
        assert ("MediaSources" in result) == ("MediaSources" in document)


def test_create_app_default_assembly_changes_no_playback_field() -> None:
    def upstream(request: Request, transaction: int) -> httpx.Response:
        del request, transaction
        return httpx.Response(
            200,
            json={"ServerName": "Upstream", "MediaSources": [REMOTE_SOURCE.copy()]},
        )

    app, patcher = _app_with_fake_upstream(upstream)
    try:
        with TestClient(app) as client:
            # The assembly keeps the rule extension point but installs no
            # implicit field-modifying rule.
            assert app.state.dispatcher._playback._service._media_source_service.rules == ()
            response = client.post("/Items/item-id/PlaybackInfo")
            document = json.loads(response.content)

            assert document["ServerName"] == "Upstream"
            assert document["MediaSources"][0] == REMOTE_SOURCE
            assert document["MediaSources"][0]["Protocol"] == "Http"
            assert document["MediaSources"][0]["SupportsTranscoding"] is True

            redirect = client.get(
                "/Videos/item-id/stream.mkv",
                params={"MediaSourceId": "source-id"},
                follow_redirects=False,
            )
            assert redirect.status_code == 302
            assert redirect.headers["location"] == REMOTE_SOURCE["Path"]
    finally:
        patcher.stop()


def test_create_app_explicit_field_configuration_changes_only_listed_fields() -> None:
    def upstream(request: Request, transaction: int) -> httpx.Response:
        del request, transaction
        return httpx.Response(
            200,
            json={"ServerName": "Upstream", "MediaSources": [REMOTE_SOURCE.copy()]},
        )

    app, patcher = _app_with_fake_upstream(
        upstream,
        playback_info_response_fields={"ServerName": "Proxy"},
        playback_info_media_source_fields={
            "Protocol": "File",
            "SupportsTranscoding": False,
        },
    )
    try:
        with TestClient(app) as client:
            document = json.loads(client.post("/Items/item-id/PlaybackInfo").content)
            source = document["MediaSources"][0]

            assert document["ServerName"] == "Proxy"
            assert source["Protocol"] == "File"
            assert source["SupportsTranscoding"] is False
            assert source["SupportsDirectPlay"] is True
            assert source["EncoderProtocol"] == "Hls"
            assert source["MediaStreams"] == [{"Codec": "hevc"}]
            assert source["Id"] == "source-id"
            assert source["Path"] == REMOTE_SOURCE["Path"]

            redirect = client.get(
                "/Videos/item-id/stream.mkv",
                params={"MediaSourceId": "source-id"},
                follow_redirects=False,
            )
            assert redirect.status_code == 302
            assert redirect.headers["location"] == REMOTE_SOURCE["Path"]
    finally:
        patcher.stop()


def test_create_app_playback_bypass_skips_overrides_and_seeds_upstream_mapping() -> None:
    original = json.dumps(
        {"ServerName": "Upstream", "MediaSources": [REMOTE_SOURCE]},
        indent=2,
    ).encode("utf-8")

    def upstream(request: Request, transaction: int) -> httpx.Response:
        del request, transaction
        return httpx.Response(200, content=original, headers={"content-type": "application/json"})

    app, patcher = _app_with_fake_upstream(
        upstream,
        playback_info_response_fields={"ServerName": "Proxy"},
        playback_info_media_source_fields={"Protocol": "File", "SupportsTranscoding": False},
    )
    try:
        with TestClient(app) as client:
            app.state.dispatcher._client_policy = ClientPolicy(
                (),
                playback_bypass_clients=("BypassClient",),
            )
            bypassed = client.post(
                "/Items/item-id/PlaybackInfo",
                headers={"x-emby-client": "BypassClient"},
            )
            # Byte-identical to the upstream body: no field override is applied.
            assert bypassed.content == original

            redirect = client.get(
                "/Videos/item-id/stream.mkv",
                params={"MediaSourceId": "source-id"},
                follow_redirects=False,
            )
            assert redirect.status_code == 302
            assert redirect.headers["location"] == REMOTE_SOURCE["Path"]

            # A non-bypassing client still receives the configured fields.
            modified = json.loads(client.post("/Items/item-id/PlaybackInfo").content)
            assert modified["ServerName"] == "Proxy"
            assert modified["MediaSources"][0]["Protocol"] == "File"
    finally:
        patcher.stop()


def test_create_app_field_overrides_stay_isolated_across_requests() -> None:
    def upstream(request: Request, transaction: int) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={
                "transaction": transaction,
                "MediaSources": [{
                    "Id": f"source-{transaction}",
                    "Path": f"https://media.example/{transaction}.mkv",
                }],
            },
        )

    app, patcher = _app_with_fake_upstream(
        upstream,
        playback_info_response_fields={"Metadata": {"tags": ["proxy"]}},
        playback_info_media_source_fields={"Tags": ["proxy"]},
    )
    try:
        with TestClient(app) as client:
            first = json.loads(client.post("/Items/item-id/PlaybackInfo").content)
            first["Metadata"]["tags"].append("mutated")
            first["MediaSources"][0]["Tags"].append("mutated")

            second = json.loads(client.post("/Items/item-id/PlaybackInfo").content)

            assert second["transaction"] == 2
            assert second["Metadata"] == {"tags": ["proxy"]}
            assert second["MediaSources"][0]["Tags"] == ["proxy"]
    finally:
        patcher.stop()


def test_create_app_field_overrides_stay_isolated_across_concurrent_requests() -> None:
    def upstream(request: Request, transaction: int) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={
                "transaction": transaction,
                "MediaSources": [{
                    "Id": f"source-{transaction}",
                    "Path": f"https://media.example/{transaction}.mkv",
                }],
            },
        )

    app, patcher = _app_with_fake_upstream(
        upstream,
        playback_info_media_source_fields={"Tags": ["proxy"], "Id": "rewritten"},
    )

    async def scenario() -> list[httpx.Response]:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://proxy"
            ) as client:
                return await asyncio.gather(*[
                    client.post(
                        "/Items/abcdef0123456789abcdef0123456789/PlaybackInfo",
                        headers={"X-Emby-Device-Id": f"device-{index}"},
                    )
                    for index in range(4)
                ])

    try:
        responses = asyncio.run(scenario())
    finally:
        patcher.stop()

    upstream_client = app.state.dispatcher._playback._http_client  # type: ignore[attr-defined]
    assert len(upstream_client.calls) == 4
    documents = [json.loads(response.content) for response in responses]
    assert sorted(document["transaction"] for document in documents) == [1, 2, 3, 4]
    for document in documents:
        source = document["MediaSources"][0]
        assert source["Tags"] == ["proxy"]
        assert source["Id"] == "rewritten"
        assert source["Path"] == f"https://media.example/{document['transaction']}.mkv"
        source["Tags"].append("mutated")
    assert all(
        source["Tags"] == ["proxy"]
        for source in (
            json.loads(response.content)["MediaSources"][0] for response in responses
        )
    )


def test_field_names_are_literal_and_case_sensitive() -> None:
    document = {"MediaSources": [{
        "Id": "source-id",
        "Path": "https://media.example/movie.mkv",
        "Protocol": "Http",
    }]}
    service = playback_service_with_fields(media_source_fields={
        "protocol": "File",
        "Some.Dotted": 1,
    })

    source = asyncio.run(service.modify(document))["MediaSources"][0]

    # No dotted-path or case folding: two literal, distinct field names are added.
    assert source["protocol"] == "File"
    assert source["Protocol"] == "Http"
    assert source["Some.Dotted"] == 1
    assert "Some" not in source


def test_conflicting_overridden_id_follows_existing_cache_semantics() -> None:
    cache = MediaSourceCache()
    cache.remember("source-b", "https://media.example/b-stale.mkv")
    service = PlaybackService(
        MediaSourceService(MediaResolver()),
        cache,
        PlaybackFieldOverrides(media_source_fields={"Id": "source-b"}),
    )
    document = {"MediaSources": [{
        "Id": "source-a",
        "Path": "https://media.example/a.mkv",
    }]}

    source = asyncio.run(service.modify(document))["MediaSources"][0]

    # Both sources now claim one ID; the existing remember() rules decide the
    # stored path. Nothing else is cleaned up.
    assert source["Id"] == "source-b"
    assert cache.get("source-a") is None
    assert cache.get("source-b") == "https://media.example/a.mkv"
