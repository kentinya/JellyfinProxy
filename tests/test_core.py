from __future__ import annotations

import asyncio
import gzip
import json

import httpx
import pytest
from fastapi import Request, Response

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
from services.playback_service import PlaybackService
from services.playback_info_cache import PlaybackInfoCache


class RewriteRule:
    def evaluate(self, source, media_url):
        if media_url.host == "alist.example.com":
            return MediaSourceDecision(
                MediaSourceAction.REWRITE,
                media_url.url.replace("alist.example.com", "cdn.example.com"),
            )
        return None


def test_playback_handler_serves_repeated_post_from_cache() -> None:
    class CountingClient:
        calls = 0

        async def forward(self, request: Request) -> httpx.Response:
            self.calls += 1
            return httpx.Response(
                200,
                json={"MediaSources": [{
                    "Id": "source-id",
                    "Path": "https://media.example/movie.mkv",
                }]},
            )

    def request(
        device_id: bytes = b"android-device",
        body: bytes = b'{"DeviceProfile":{"Name":"Android"}}',
        api_key: bytes = b"first-token",
        path: str = "/Items/item-id/PlaybackInfo",
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

    client = CountingClient()
    handler = PlaybackHandler(
        client,  # type: ignore[arg-type]
        PlaybackService(MediaSourceService(MediaResolver())),
        PlaybackInfoCache(),
    )

    first = asyncio.run(handler.handle(request()))
    second = asyncio.run(handler.handle(request(
        device_id=b"television-device",
        body=b'{"DeviceProfile":{"Name":"Android TV"}}',
        api_key=b"second-token",
    )))

    assert client.calls == 1
    assert first.headers["x-jellyfinproxy-cache"] == "MISS"
    assert second.headers["x-jellyfinproxy-cache"] == "HIT"
    assert second.body == first.body


@pytest.mark.parametrize("cache_mode", ["miss", "hit", "disabled"])
def test_bypassed_playback_preserves_body_and_populates_video_redirect(cache_mode) -> None:
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

    cache = PlaybackInfoCache()
    client = Client()
    service = PlaybackService(MediaSourceService(MediaResolver(), [ProtocolFileRule()]))
    handler = PlaybackHandler(client, service, cache)
    playback_request = request("/Items/item-id/PlaybackInfo")
    if cache_mode == "hit":
        cache.remember(asyncio.run(handler._cache_key(playback_request)), original)
    response = asyncio.run(handler.handle(
        playback_request, modify=False, use_cache=cache_mode != "disabled",
    ))
    assert response.body == original
    assert client.calls == (0 if cache_mode == "hit" else 1)

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
        self.cache = PlaybackInfoCache()
        self.service = PlaybackService(
            MediaSourceService(MediaResolver(), [ProtocolFileRule()]),
        )
        self.handler = PlaybackHandler(self, self.service, self.cache)  # type: ignore[arg-type]

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

    def prefilled_playback(self, **kwargs) -> Response:
        """Fill the JSON cache, then serve it from the cache (HIT) path."""
        probe = self.request()
        asyncio.run(self.handler.handle(probe, **kwargs))
        return asyncio.run(self.handler.handle(probe, **kwargs))


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


@pytest.mark.parametrize("cache_mode", ["miss", "hit", "disabled"])
@pytest.mark.parametrize("modify", [True, False])
@pytest.mark.parametrize("path", INVALID_PIPELINE_PATHS)
def test_playback_pipeline_clears_stale_mapping_for_invalid_path(
    cache_mode, modify, path
) -> None:
    body = playback_document(path)
    pipeline = PlaybackPipeline(body)
    pipeline.service.media_source_cache.remember("source-id", OLD_VIDEO_URL)

    if cache_mode == "hit":
        response = pipeline.prefilled_playback(modify=modify)
        assert pipeline.calls == 1
        assert response.headers["x-jellyfinproxy-cache"] == "HIT"
    else:
        response = pipeline.playback(
            pipeline.request(), modify=modify, use_cache=cache_mode != "disabled",
        )
        assert pipeline.calls == 1
        if cache_mode == "miss":
            assert response.headers["x-jellyfinproxy-cache"] == "MISS"

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
        ("/emby/api/danmu/source-id/raw", b""),
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
    pytest.param("/emby/api/danmu/source-id/raw", b"", id="emby-danmu-raw"),
    pytest.param("/api/danmu/source-id/raw", b"", id="danmu-raw"),
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


def test_playback_cache_normalizes_emby_and_uuid_path_variants() -> None:
    class CountingClient:
        calls = 0

        async def forward(self, request: Request) -> httpx.Response:
            self.calls += 1
            return httpx.Response(200, json={"MediaSources": []})

    def request(path: str) -> Request:
        return Request({
            "type": "http", "method": "POST", "scheme": "http",
            "server": ("proxy", 8097), "path": path,
            "query_string": b"", "headers": [],
        })

    client = CountingClient()
    handler = PlaybackHandler(
        client,  # type: ignore[arg-type]
        PlaybackService(MediaSourceService(MediaResolver())),
        PlaybackInfoCache(),
    )
    compact = "/emby/Items/c7abcb3401d22d5cd3fd058cc914bdcf/PlaybackInfo"
    hyphenated = "/Items/c7abcb34-01d2-2d5c-d3fd-058cc914bdcf/PlaybackInfo"

    asyncio.run(handler.handle(request(compact), modify=False))
    hit = asyncio.run(handler.handle(request(hyphenated)))

    assert client.calls == 1
    assert hit.headers["x-jellyfinproxy-cache"] == "HIT"


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
    assert router.match("/emby/api/danmu/source-id/raw", "GET") is HandlerType.VIDEO
    assert router.match("/api/danmu/source-id/raw", "GET") is HandlerType.VIDEO


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


def test_video_handler_uses_emby_danmu_raw_path_id() -> None:
    class FailingProxy:
        async def handle(self, request: Request) -> Response:
            raise AssertionError(f"unexpected proxy fallback for {request.url.path}")

    cache = MediaSourceCache()
    cache.remember("source-id", "https://media.example/movie.mkv")
    request = Request({
        "type": "http",
        "method": "GET",
        "scheme": "http",
        "server": ("proxy", 8097),
        "path": "/emby/api/danmu/source-id/raw",
        "query_string": b"",
        "headers": [],
    })

    response = asyncio.run(VideoHandler(FailingProxy(), cache).handle(request))  # type: ignore[arg-type]

    assert response.status_code == 302
    assert response.headers["location"] == "https://media.example/movie.mkv"


def test_video_handler_uses_danmu_raw_path_without_emby_prefix() -> None:
    class FailingProxy:
        async def handle(self, request: Request) -> Response:
            raise AssertionError(f"unexpected proxy fallback for {request.url.path}")

    cache = MediaSourceCache()
    cache.remember("source-id", "https://media.example/movie.mkv")
    request = Request({
        "type": "http",
        "method": "GET",
        "scheme": "http",
        "server": ("proxy", 8097),
        "path": "/api/danmu/source-id/raw",
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


def test_client_can_bypass_playback_cache_independently() -> None:
    policy = ClientPolicy(
        (),
        playback_cache_bypass_clients=("No Cache Client",),
    )
    headers = {"user-agent": "No Cache Client/1.0"}
    assert policy.should_bypass_playback_cache(headers)
    assert not policy.should_bypass(headers, HandlerType.PLAYBACK)


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
