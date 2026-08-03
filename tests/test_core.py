from __future__ import annotations

import asyncio
import gzip

import httpx
from fastapi import Request, Response

from handlers.video_handler import VideoHandler
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


class RewriteRule:
    def evaluate(self, source, media_url):
        if media_url.host == "alist.example.com":
            return MediaSourceDecision(
                MediaSourceAction.REWRITE,
                media_url.url.replace("alist.example.com", "cdn.example.com"),
            )
        return None


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


def test_video_handler_redirects_to_cached_media_source_path() -> None:
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
        "query_string": b"MediaSourceId=source-id",
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


def test_client_bypass_is_case_insensitive_across_headers() -> None:
    policy = ClientPolicy(("Infuse", "Kodi"))
    assert policy.should_bypass({"user-agent": "Infuse/8"})
    assert policy.should_bypass({"x-emby-client": "kodi"})
    assert not policy.should_bypass({"user-agent": "Jellyfin Web"})


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
