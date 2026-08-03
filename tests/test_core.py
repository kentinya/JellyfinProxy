from __future__ import annotations

import asyncio
import gzip

import httpx

from handlers.proxy_handler import response_headers
from policies.client_policy import ClientPolicy
from routers.route_config import HandlerType
from routers.router import Router
from services.media_resolver import MediaResolver
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
    assert router.match("/Items/abc/PlaybackInfo", "POST") is HandlerType.PLAYBACK
    assert router.match("/Items/abc/PlaybackInfo", "PUT") is HandlerType.DEFAULT
    for path in ("/Videos/id/stream", "/Videos/id/stream.mp4", "/Videos/id/master.m3u8", "/Videos/id/hls/a.ts"):
        assert router.match(path, "GET") is HandlerType.VIDEO


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
        headers={"Content-Encoding": "gzip", "Content-Length": "100", "X-Test": "kept"},
        content=gzip.compress(b"decoded body"),
    )
    headers = response_headers(upstream)
    assert "content-encoding" not in headers
    assert "content-length" not in headers
    assert headers["x-test"] == "kept"
