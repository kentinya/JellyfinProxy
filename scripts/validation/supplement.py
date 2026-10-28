"""Functional supplement evidence for Task S1.1 (V1 .. V4).

Only the product entry points that already exist in the fixed Slice Base product
are exercised (PlaybackInfo, Video stream, danmu raw) against the isolated real
Jellyfin 12.3 server. No product capability, route or endpoint is added, and no
upstream response is synthesised:

* ``J``     -- the real 12.3 server contacted directly (no observatory, no proxy)
* ``B-on``  -- extracted fixed Base product, original JSON cache enabled
* ``B-off`` -- same source, only ``playback_info_cache_enabled`` disabled

Both product groups are started from the run directory with the filtered
environment and the real product TOML written by :mod:`proxy_runner`; the client
bypass matrix is the product's own configuration.

Each check records the request, the observed status / headers, the controlled
media-origin ledger entry belonging to the same transaction, and an explicit
PASS / FAIL / BLOCKED decision. Media bodies are never accumulated: streaming
evidence uses bounded reads plus the origin's own socket ledger.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Mapping

import httpx

if __package__ in (None, ""):
    # Allow ``python scripts/validation/supplement.py`` like the other tools.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.validation import fixtures
from scripts.validation.client import identity_headers
from scripts.validation.common import (
    ValidationError,
    ensure_directory,
    passthrough_matches_upstream,
    sha256_bytes,
    utc_now,
    write_json,
)
from scripts.validation.environment import (
    JellyfinContainer,
    RunPaths,
    assert_owned_run_dir,
    load_manifest,
    tool_identity,
    update_manifest,
    wait_for_jellyfin,
)
from scripts.validation.media_server import MediaServer
from scripts.validation.proxy_runner import ProcessSupervisor, launch_proxy, toml_dumps

#: Real product configuration: both single-route and overlapping bypass lists.
PROFILE = "matrix_overlap"
GROUP_CACHE = {"B-on": True, "B-off": False}

#: The throttled fixture is reused at a slower rate so that a client abort
#: provably happens while the origin still has bytes to write.
THROTTLE_TARGET = "remote-a.mp4?throttle=8000"


class Recorder:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.checks: list[dict[str, Any]] = []

    def add(
        self,
        check_id: str,
        group: str,
        expected: str,
        observed: Mapping[str, Any],
        *,
        ac: str,
        status: str | None = None,
        notes: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        entry = {
            "id": check_id,
            "group": group,
            "ac": ac,
            "expected": expected,
            "observed": dict(observed),
            "status": status or ("PASS" if observed.get("ok") else "FAIL"),
            "notes": list(notes),
            "recorded_at": utc_now(),
        }
        self.checks.append(entry)
        write_json(self.path, self.checks, mode=0o600)
        print(f"  [{entry['status']:4}] {check_id} ({group})", flush=True)
        return entry

    @property
    def failures(self) -> list[dict[str, Any]]:
        return [check for check in self.checks if check["status"] != "PASS"]


def _digest(value: Any) -> str | None:
    return sha256_bytes(str(value).encode())[:16] if value else None


def _auth_headers(credentials: fixtures.Credentials, client: str) -> dict[str, str]:
    return identity_headers(
        client,
        "s1-device-alpha",
        device_id="s1-device-alpha",
        token=credentials.users["s1user1"]["token"],
    )


class Session:
    """One HTTP client bound to a single control group base URL."""

    def __init__(self, group: str, base_url: str, credentials: fixtures.Credentials) -> None:
        self.group = group
        self.base_url = base_url.rstrip("/")
        self.credentials = credentials
        self.client = httpx.Client(timeout=30.0, follow_redirects=False)

    def close(self) -> None:
        self.client.close()

    # -- product entry points ------------------------------------------
    def playback_info(self, item_id: str, client_name: str = "PlainClient") -> dict[str, Any]:
        response = self.client.get(
            f"{self.base_url}/Items/{item_id}/PlaybackInfo",
            headers=_auth_headers(self.credentials, client_name),
        )
        document: Any = None
        try:
            document = response.json()
        except ValueError:
            document = None
        sources = document.get("MediaSources") if isinstance(document, dict) else None
        source = sources[0] if sources else {}
        return {
            "status": response.status_code,
            "cache_header": response.headers.get("x-jellyfinproxy-cache"),
            "source_id": source.get("Id"),
            "protocol": source.get("Protocol"),
            "supports_transcoding": source.get("SupportsTranscoding"),
            "path_digest": _digest(source.get("Path")),
            "source_count": len(sources or []),
        }

    def video(self, path: str, client_name: str = "PlainClient") -> dict[str, Any]:
        response = self.client.get(
            f"{self.base_url}{path}", headers=_auth_headers(self.credentials, client_name)
        )
        return {
            "path": path,
            "status": response.status_code,
            "location": response.headers.get("location"),
            "location_digest": _digest(response.headers.get("location")),
            "content_type": response.headers.get("content-type"),
            "body_bytes": len(response.content),
            "body_sha256": sha256_bytes(response.content),
        }

    def get(self, path: str) -> dict[str, Any]:
        response = self.client.get(f"{self.base_url}{path}")
        return {
            "path": path,
            "status": response.status_code,
            "location_digest": _digest(response.headers.get("location")),
            "body_bytes": len(response.content),
        }

    def stream_prefix_then_abort(
        self,
        path: str,
        *,
        client_name: str = "VideoOnly",
        max_bytes: int = 8192,
    ) -> dict[str, Any]:
        """Read a bounded prefix of a real stream, then close the connection."""

        started = time.monotonic()
        read = 0
        status = 0
        headers: dict[str, str] = {}
        error: str | None = None
        try:
            with self.client.stream(
                "GET",
                f"{self.base_url}{path}",
                headers=_auth_headers(self.credentials, client_name),
            ) as response:
                status = response.status_code
                headers = {key.casefold(): value for key, value in response.headers.items()}
                for chunk in response.iter_raw():
                    read += len(chunk)
                    if read >= max_bytes:
                        break
            # Leaving the stream context closes the socket, which is the abort.
            abort_closed = True
        except httpx.HTTPError as exc:
            error = type(exc).__name__
            abort_closed = True
        return {
            "path": path,
            "client_identity": client_name,
            "status": status,
            "bytes_read_before_abort": read,
            "content_length": headers.get("content-length"),
            "content_range": headers.get("content-range"),
            "location_present": "location" in headers,
            "abort_closed_connection": abort_closed,
            "abort_error": error,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
        }


class Context:
    def __init__(
        self,
        *,
        paths: RunPaths,
        container: JellyfinContainer,
        credentials: fixtures.Credentials,
        catalog: Mapping[str, Any],
        origin: MediaServer,
        media_port: int,
        proxy_config: Mapping[str, Any] | None = None,
    ) -> None:
        self.paths = paths
        self.container = container
        self.credentials = credentials
        self.catalog = catalog
        self.origin = origin
        self.media_port = media_port
        #: The real product TOML the control groups were started with.
        self.proxy_config: dict[str, Any] = dict(proxy_config or {})

    def remote_url(self, target: str) -> str:
        return f"http://{self.container.gateway}:{self.media_port}/{target.lstrip('/')}"


def _media_url(catalog: Mapping[str, Any], key: str) -> str:
    sources = catalog[key].get("media_sources") or [{}]
    return str(sources[0].get("path") or "")


def _origin_window(
    origin: MediaServer,
    since: float,
    *,
    expect_entries: int = 1,
    timeout: float = 15.0,
) -> list[dict[str, Any]]:
    """Entries recorded at or after ``since``, waiting for the ledger to catch up.

    The controlled origin appends an entry when a transfer ends, so an aborted
    transfer is only visible once its socket write fails. Waiting keeps a slow
    release from being reported as "no upstream request at all".
    """

    deadline = time.monotonic() + timeout
    entries = [entry for entry in origin.state.snapshot() if entry["timestamp"] >= since]
    while len(entries) < expect_entries and time.monotonic() < deadline:
        time.sleep(0.25)
        entries = [entry for entry in origin.state.snapshot() if entry["timestamp"] >= since]
    return entries


def _origin_summary(entries: list[dict[str, Any]], full_size: int) -> dict[str, Any]:
    sent = [entry.get("bytes_sent") or 0 for entry in entries]
    return {
        "requests": entries,
        "entries": len(entries),
        "bytes_sent": sent,
        "max_bytes_sent": max(sent) if sent else 0,
        "any_aborted_by_reader": any(entry.get("aborted_by_client") for entry in entries),
        "any_finished": any(entry.get("finished") for entry in entries),
        "full_size": full_size,
        "released_before_full_size": bool(sent) and min(sent) < full_size,
    }


# ---------------------------------------------------------------------------
# real fixture transitions (STRM rewrite + library refresh, as in the baseline)
# ---------------------------------------------------------------------------


def rewrite_strm(
    ctx: Context,
    key: str,
    value: str,
    *,
    remove_first: bool = True,
) -> dict[str, Any]:
    entry = next(item for item in fixtures.MEDIA_LAYOUT if item["key"] == key)
    target = ctx.paths.media / "movies" / entry["folder"] / entry["file"]
    started = time.monotonic()
    if remove_first:
        if target.exists():
            target.unlink()
        fixtures.refresh_library(ctx.container, ctx.credentials, timeout=300)
    fixtures.write_strm(ctx.paths, key, value)
    fixtures.refresh_library(ctx.container, ctx.credentials, timeout=300)
    return {
        "target_digest": _digest(value),
        "remove_before_write": remove_first,
        "seconds": round(time.monotonic() - started, 2),
    }


# ---------------------------------------------------------------------------
# V2: bypass matrix, id priority, raw fallback
# ---------------------------------------------------------------------------


def check_raw_unseeded(
    ctx: Context,
    session: Session,
    recorder: Recorder,
    *,
    direct_j: Session,
) -> None:
    """Both raw entries must stay transparent before and after mapping seeding."""

    item_id = ctx.catalog["remote_two"]["id"]
    for label, path in (
        ("raw", f"/api/danmu/{item_id}/raw"),
        ("emby_raw", f"/emby/api/danmu/{item_id}/raw"),
    ):
        observed = session.video(path)
        baseline = direct_j.video(path)
        observed["jellyfin_direct"] = baseline
        observed["ok"] = passthrough_matches_upstream(observed, baseline)
        recorder.add(
            f"V2-raw-unseeded-{label}",
            session.group,
            "an unseeded media source id reaches Jellyfin unchanged (no proxy 302, same status, body and Content-Type as direct J)",
            observed,
            ac="AC-6, AC-9",
            notes=(
                "recorded before this proxy process ever requested PlaybackInfo for that item",
                "the direct Jellyfin row is the identical path against the real 12.3 server",
            ),
        )

    seeded = session.playback_info(item_id, "CacheOnly")
    for label, path in (
        ("raw", f"/api/danmu/{item_id}/raw"),
        ("emby_raw", f"/emby/api/danmu/{item_id}/raw"),
    ):
        after = session.video(path)
        baseline = direct_j.video(path)
        after["seed"] = seeded
        after["jellyfin_direct"] = baseline
        after["ok"] = (
            seeded["status"] == 200
            and passthrough_matches_upstream(after, baseline)
        )
        recorder.add(
            f"V2-raw-after-seeding-{label}",
            session.group,
            "after the same id is seeded by a real PlaybackInfo response, the raw entry still matches direct J",
            after,
            ac="AC-6",
            notes=(
                "a 302 to the seeded URL is the removed behaviour and must now FAIL, not pass",
                "an upstream-originated Location is accepted only when direct J returns the same one",
            ),
        )


def check_bypass_matrix(
    ctx: Context,
    session: Session,
    recorder: Recorder,
    *,
    direct_j: Session,
) -> None:
    """Real global / per-route / overlapping bypass configuration."""

    item = ctx.catalog["remote"]
    item_id = item["id"]
    source_id = (item["media_sources"] or [{}])[0].get("id") or item_id
    stream = f"/Videos/{item_id}/stream?static=true&MediaSourceId={source_id}"

    plain_info = session.playback_info(item_id, "PlainClient")
    global_info = session.playback_info(item_id, "GlobalClient")
    overlap_info = session.playback_info(item_id, "OverlapClient")
    plain_video = session.video(stream, "PlainClient")
    global_video = session.video(stream, "GlobalClient")
    overlap_video = session.video(stream, "OverlapClient")
    direct_info = direct_j.playback_info(item_id, "PlainClient")
    direct_video = direct_j.video(stream, "PlainClient")

    observed = {
        "plain_playback": plain_info,
        "global_playback": global_info,
        "overlap_playback": overlap_info,
        "jellyfin_direct_playback": direct_info,
        "plain_video": plain_video,
        "global_video": global_video,
        "overlap_video": overlap_video,
        "jellyfin_direct_video": direct_video,
        "overlap_client_listed_in": {
            "bypass_clients": "OverlapClient" in (ctx.proxy_config.get("bypass_clients") or []),
            "playback_bypass_clients": "OverlapClient"
            in (ctx.proxy_config.get("playback_bypass_clients") or []),
            "video_bypass_clients": "OverlapClient" in (ctx.proxy_config.get("video_bypass_clients") or []),
        },
    }
    observed["ok"] = (
        plain_info["status"] == 200
        and plain_info["protocol"] == "File"
        and plain_info["supports_transcoding"] is False
        and global_info["protocol"] == direct_info["protocol"]
        and overlap_info["protocol"] == direct_info["protocol"]
        and plain_video["status"] == 302
        and plain_video["location_digest"] == _digest(_media_url(ctx.catalog, "remote"))
        and global_video["status"] == direct_video["status"] == 200
        and overlap_video["status"] == direct_video["status"] == 200
        and not global_video["location_digest"]
        and not overlap_video["location_digest"]
        and all(observed["overlap_client_listed_in"].values())
    )
    recorder.add(
        "V2-bypass-global-and-overlap",
        session.group,
        "the global client bypasses both routes, a client listed in the global table and in both route tables "
        "bypasses too, and the plain client is still rewritten and redirected",
        observed,
        ac="AC-3, AC-5, AC-6",
        notes=(
            "configuration is the real product TOML (matrix_overlap profile) written by the tool",
            "OverlapClient appears in bypass_clients *and* in both per-route lists, so this is the configured "
            "global / branch overlap rather than two disjoint lists",
            "direct Jellyfin rows are the same requests without the proxy",
        ),
    )

    video_only = session.video(stream, "VideoOnly")
    cache_only = session.playback_info(item_id, "CacheOnly")
    observed_video = {
        "video_only_video": video_only,
        "cache_only_playback": cache_only,
        "jellyfin_direct_video": direct_video,
    }
    observed_video["ok"] = (
        video_only["status"] == direct_video["status"] == 200
        and not video_only["location_digest"]
        and cache_only["protocol"] == "File"
    )
    recorder.add(
        "V2-bypass-route-independence",
        session.group,
        "a video-only bypass client leaves the video route unmodified while PlaybackInfo is still modified",
        observed_video,
        ac="AC-6",
    )


def check_id_resolution(ctx: Context, session: Session, recorder: Recorder) -> None:
    """Two genuinely seeded sources: query/path priority and both UUID forms."""

    a_id = ctx.catalog["remote"]["id"]
    b_id = ctx.catalog["remote_two"]["id"]
    digest_a = _digest(_media_url(ctx.catalog, "remote"))
    digest_b = _digest(_media_url(ctx.catalog, "remote_two"))
    hyphenated = f"{b_id[0:8]}-{b_id[8:12]}-{b_id[12:16]}-{b_id[16:20]}-{b_id[20:32]}"

    # Seed both ids inside this check so the conflict rows below never depend on
    # an earlier scenario's request order.
    seeds = {
        "remote": session.playback_info(a_id, "CacheOnly"),
        "remote_two": session.playback_info(b_id, "CacheOnly"),
    }

    cases = {
        "query_wins_over_path": (f"/Videos/{a_id}/stream?static=true&MediaSourceId={b_id}", digest_b),
        "query_same_as_path": (f"/Videos/{a_id}/stream?static=true&MediaSourceId={a_id}", digest_a),
        "path_only": (f"/Videos/{b_id}/stream?static=true", digest_b),
        "query_uuid_hyphenated": (
            f"/Videos/{a_id}/stream?static=true&MediaSourceId={hyphenated}",
            digest_b,
        ),
        "query_uuid_compact": (
            f"/Videos/{a_id}/stream?static=true&MediaSourceId={b_id}",
            digest_b,
        ),
    }
    # Both query spellings of the same parameter in one URL, pointing at two
    # different seeded sources. The product reads ``MediaSourceId`` first and only
    # falls back to ``mediaSourceId``, so the exact-name occurrence decides the
    # target no matter which one appears first; the rows swap both the order and
    # which spelling carries which id to show that.
    conflict_cases = {
        "conflict_exact_a_then_lower_b": (
            f"/Videos/{a_id}/stream?static=true&MediaSourceId={a_id}&mediaSourceId={b_id}",
            digest_a,
        ),
        "conflict_lower_b_then_exact_a": (
            f"/Videos/{a_id}/stream?static=true&mediaSourceId={b_id}&MediaSourceId={a_id}",
            digest_a,
        ),
        "conflict_exact_b_then_lower_a": (
            f"/Videos/{b_id}/stream?static=true&MediaSourceId={b_id}&mediaSourceId={a_id}",
            digest_b,
        ),
        "conflict_lower_a_then_exact_b": (
            f"/Videos/{b_id}/stream?static=true&mediaSourceId={a_id}&MediaSourceId={b_id}",
            digest_b,
        ),
    }
    observed: dict[str, Any] = {
        "seeds": seeds,
        "seeded_targets": {"remote": digest_a, "remote_two": digest_b},
        "hyphenated_query_length": len(hyphenated),
        "priority_rule": (
            "the exact query name MediaSourceId wins over mediaSourceId regardless of order, and either "
            "spelling still wins over the path id"
        ),
        "cases": {},
        "conflict_cases": {},
    }
    all_ok = (
        seeds["remote"]["status"] == 200 and seeds["remote_two"]["status"] == 200
    )
    for label, (path, expected) in cases.items():
        row = session.video(path)
        row["expected_digest"] = expected
        row["ok"] = row["status"] == 302 and row["location_digest"] == expected
        all_ok = all_ok and row["ok"]
        observed["cases"][label] = row
    for label, (path, expected) in conflict_cases.items():
        row = session.video(path)
        row["expected_digest"] = expected
        row["ok"] = row["status"] == 302 and row["location_digest"] == expected
        all_ok = all_ok and row["ok"]
        observed["conflict_cases"][label] = row
    observed["ok"] = all_ok
    recorder.add(
        "V2-id-priority-and-uuid",
        session.group,
        "with two real seeded sources the query id wins over the path id, both UUID spellings resolve, and a URL "
        "carrying two conflicting query names resolves to the exact MediaSourceId spelling",
        observed,
        ac="AC-6, AC-9",
        notes=(
            "both ids were seeded by their own real PlaybackInfo response at the start of this check",
            "the conflict rows put two different real seeded ids in the same Video URL and swap both the order and "
            "which spelling carries which id, then compare the resulting Location digest",
        ),
    )


# ---------------------------------------------------------------------------
# V1: a second seeded mapping survives the target's valid/invalid/valid cycle
# ---------------------------------------------------------------------------


def check_second_mapping_preserved(
    ctx: Context,
    session: Session,
    recorder: Recorder,
    *,
    direct_j: Session,
) -> None:
    dynamic_id = ctx.catalog["dynamic"]["id"]
    dynamic_source = (ctx.catalog["dynamic"]["media_sources"] or [{}])[0].get("id") or dynamic_id
    # The second mapping deliberately keeps a different target (remote-a) from the
    # dynamic item's final target (remote-b), so the last step distinguishes them.
    second_id = ctx.catalog["remote"]["id"]
    second_source = (ctx.catalog["remote"]["media_sources"] or [{}])[0].get("id") or second_id
    dynamic_stream = f"/Videos/{dynamic_id}/stream?static=true&MediaSourceId={dynamic_source}"
    second_stream = f"/Videos/{second_id}/stream?static=true&MediaSourceId={second_source}"
    digest_second = _digest(_media_url(ctx.catalog, "remote"))
    digest_a = _digest(_media_url(ctx.catalog, "remote"))
    digest_b = _digest(_media_url(ctx.catalog, "remote_two"))
    invalid_local = "/media/movies/Local/Local Sample (2020)/Local Sample (2020).mp4"

    # Seed the second mapping *before* the target cycle and then never request its
    # PlaybackInfo again: any PlaybackInfo response (HIT included) re-writes the
    # mapping, so only a Video-only check can show that the seeded entry survived.
    second_seed = session.playback_info(second_id, "CacheOnly")
    seeded_video = session.video(second_stream)
    seed_ok = (
        second_seed["status"] == 200
        and seeded_video["status"] == 302
        and seeded_video["location_digest"] == digest_second
    )

    steps: list[dict[str, Any]] = []
    sequence_ok = True

    def step(label: str, target: str | None, expected: str | None) -> None:
        nonlocal sequence_ok
        transition = rewrite_strm(ctx, "dynamic", target) if target else {"value_digest": None}
        target_playback = session.playback_info(dynamic_id)
        target_bypass = session.playback_info(dynamic_id, "CacheOnly")
        target_video = session.video(dynamic_stream)
        second_video = session.video(second_stream)
        second_ok = (
            second_video["status"] == 302
            and second_video["location_digest"] == digest_second
        )
        if expected is None:
            target_ok = target_video["status"] != 302 and not target_video["location_digest"]
        else:
            target_ok = target_video["status"] == 302 and target_video["location_digest"] == expected
        sequence_ok = sequence_ok and second_ok and target_ok
        steps.append(
            {
                "step": label,
                "transition": transition,
                "target_playback": target_playback,
                "target_playback_cache_bypass": target_bypass,
                "target_video": target_video,
                "second_video": second_video,
                "second_mapping_preserved": second_ok,
                "target_behaviour_ok": target_ok,
            }
        )

    step("valid_remote_a", ctx.remote_url("remote-a.mp4"), digest_a)
    step("invalid_local_path", invalid_local, None)
    step("valid_remote_b", ctx.remote_url("remote-b.mp4"), digest_b)

    final_second = session.video(second_stream)
    observed = {
        "dynamic_item_id": dynamic_id,
        "second_item_id": second_id,
        "seeding": {
            "playback": second_seed,
            "video": seeded_video,
            "ok": seed_ok,
        },
        "second_target_digest": digest_second,
        "dynamic_final_target_digest": digest_b,
        "steps": steps,
        "final_second_video": final_second,
        "second_playback_requests_during_cycle": 0,
        "ok": seed_ok
        and sequence_ok
        and final_second["status"] == 302
        and final_second["location_digest"] == digest_second,
    }
    recorder.add(
        "V1-second-mapping-preserved",
        session.group,
        "the second mapping seeded on its own before the cycle keeps its 302 target through the dynamic item's "
        "valid -> invalid -> valid cycle, and only the target id changes",
        observed,
        ac="AC-7",
        notes=(
            "the second id is seeded once up front and no later PlaybackInfo is sent for it, so a re-populated "
            "mapping cannot be mistaken for a preserved one",
            "every transition is produced by a real library refresh (remove STRM, scan, rewrite STRM, scan)",
            "the second item keeps remote-a while the dynamic item ends at remote-b, so the last step proves the two "
            "mappings were not collapsed into one",
            "B-on may answer the plain PlaybackInfo row from its old cache; the CacheOnly row shows the real upstream result",
        ),
    )


# ---------------------------------------------------------------------------
# V3: abort a real transfer while the origin still has bytes to send
# ---------------------------------------------------------------------------


def prepare_throttled_fixture(ctx: Context, recorder: Recorder) -> None:
    transition = rewrite_strm(ctx, "throttle", ctx.remote_url(THROTTLE_TARGET), remove_first=True)
    item = ctx.catalog["throttle"]
    item["media_sources"][0]["path"] = ctx.remote_url(THROTTLE_TARGET)
    session = Session("fixture", ctx.container.base_url, ctx.credentials)
    try:
        seeded = session.playback_info(item["id"], "CacheOnly")
    finally:
        session.close()
    owned = {
        "ok": seeded["status"] == 200 and seeded["path_digest"] == _digest(ctx.remote_url(THROTTLE_TARGET)),
        "throttle_target": THROTTLE_TARGET,
        "transition": transition,
        "upstream_playback": seeded,
    }
    recorder.add(
        "V3-fixture",
        "fixture",
        "the dedicated playable item is re-pointed at the throttled origin and the real server reports the new source",
        owned,
        ac="AC-8",
        notes=(
            "the fixture keeps its real library item id and is only slowed down so the abort provably lands mid-transfer",
        ),
        status="PASS" if owned["ok"] else "BLOCKED",
    )


def check_stream_abort_release(
    ctx: Context,
    session: Session,
    recorder: Recorder,
    *,
    direct_j: Session,
) -> None:
    item = ctx.catalog["throttle"]
    item_id = item["id"]
    source_id = (item.get("media_sources") or [{}])[0].get("id") or item_id
    stream = f"/Videos/{item_id}/stream?static=true&MediaSourceId={source_id}"
    full_size = (ctx.origin.inventory().get("remote-a.mp4") or {}).get("size") or 0

    seed = session.playback_info(item_id, "CacheOnly")

    start = time.time()
    cancelled = session.stream_prefix_then_abort(stream, client_name="VideoOnly")
    during = _origin_summary(_origin_window(ctx.origin, start), full_size)

    follow_start = time.time()
    follow = session.client.get(
        f"{session.base_url}{stream}",
        headers={**_auth_headers(ctx.credentials, "VideoOnly"), "range": "bytes=0-4095"},
    )
    follow_origin = _origin_summary(_origin_window(ctx.origin, follow_start), full_size)

    direct_start = time.time()
    direct_cancel = direct_j.stream_prefix_then_abort(stream, client_name="VideoOnly")
    direct_origin = _origin_summary(_origin_window(ctx.origin, direct_start), full_size)

    declared = int(cancelled["content_length"] or 0)
    observed = {
        "seed_playback": seed,
        "source_url_digest": _digest(_media_url(ctx.catalog, "throttle")),
        "full_media_bytes": full_size,
        "cancelled_read": cancelled,
        "origin_during_cancel": during,
        "follow_up": {
            "status": follow.status_code,
            "content_range": follow.headers.get("content-range"),
            "bytes": len(follow.content),
        },
        "origin_during_follow_up": follow_origin,
        "jellyfin_direct_cancelled_read": direct_cancel,
        "origin_during_direct_cancel": direct_origin,
        "ok": (
            cancelled["bytes_read_before_abort"] > 0
            and declared >= full_size
            and during["entries"] >= 1
            and during["any_aborted_by_reader"]
            and during["released_before_full_size"]
            and max(during["bytes_sent"]) < declared
            and follow.status_code in (200, 206)
            and len(follow.content) > 0
            and follow_origin["entries"] >= 1
        ),
    }
    recorder.add(
        "V3-cancel-upstream-release",
        session.group,
        "with the origin still sending, an aborted client read releases the upstream transfer before the whole body "
        "was written, and a later request still returns real bytes",
        observed,
        ac="AC-4, AC-8",
        notes=(
            "the VideoOnly client keeps this request on the product's own streaming path instead of a proxy 302",
            "release is read from the controlled origin socket ledger, not from a buffered copy of the media",
            "the direct Jellyfin row is the identical abort without the proxy",
        ),
    )


# ---------------------------------------------------------------------------
# V4: product connected straight to Jellyfin, outage and recovery
# ---------------------------------------------------------------------------


def check_unreachable_and_recovery(
    ctx: Context,
    sessions: Mapping[str, Session],
    direct_j: Session,
    recorder: Recorder,
) -> None:
    item_id = ctx.catalog["remote"]["id"]

    def safe(call: Any) -> dict[str, Any]:
        try:
            return call()
        except httpx.HTTPError as exc:  # the product may also fail at the socket layer
            return {"status": None, "transport_error": type(exc).__name__}

    def snapshot() -> dict[str, Any]:
        rows: dict[str, Any] = {}
        for group, session in sessions.items():
            rows[group] = {
                "plain_playback": safe(lambda s=session: s.playback_info(item_id)),
                "cache_bypass_playback": safe(lambda s=session: s.playback_info(item_id, "CacheOnly")),
                "public_info": safe(lambda s=session: s.get("/System/Info/Public")),
            }
        return rows

    before = snapshot()
    direct_before = direct_j.get("/System/Info/Public")
    ctx.container.stop()
    try:
        during = snapshot()
        direct_during = safe(lambda: direct_j.get("/System/Info/Public"))
    finally:
        ctx.container.start()
        revived = wait_for_jellyfin(ctx.container, timeout=300)
    after = snapshot()
    direct_after = direct_j.get("/System/Info/Public")

    b_off_during = during.get("B-off") or {}
    b_on_during = during.get("B-on") or {}
    after_off = after.get("B-off") or {}
    after_on = after.get("B-on") or {}
    observed = {
        "item_id": item_id,
        "direct_jellyfin_before": direct_before,
        "direct_jellyfin_during_outage": direct_during,
        "direct_jellyfin_after": direct_after,
        "product_before": before,
        "product_during_outage": during,
        "product_after_recovery": after,
        "revived_version": (revived or {}).get("Version"),
        "ok": (
            str((revived or {}).get("Version", "")).startswith("12.3")
            and b_off_during.get("plain_playback", {}).get("status") != 200
            and b_off_during.get("cache_bypass_playback", {}).get("status") != 200
            and b_on_during.get("cache_bypass_playback", {}).get("status") != 200
            and after_off.get("plain_playback", {}).get("status") == 200
            and after_off.get("cache_bypass_playback", {}).get("status") == 200
            and after_on.get("cache_bypass_playback", {}).get("status") == 200
        ),
    }
    recorder.add(
        "V4-direct-unreachable-and-recovery",
        "B-off+B-on",
        "with the product pointed straight at Jellyfin, an outage produces a real product-level failure and normal "
        "service returns after the server restarts",
        observed,
        ac="AC-9, AC-5",
        notes=(
            "the product upstream is the real Jellyfin base URL; no observatory or other component answers for it",
            "a B-on cache HIT during the outage is recorded as the pre-change masking effect, not as proof of upstream availability",
            "only the task-owned container was stopped and restarted",
        ),
    )


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------


def run(run_dir: Path, *, groups: tuple[str, ...] = ("B-off", "B-on")) -> int:
    paths = RunPaths(root=run_dir.resolve())
    assert_owned_run_dir(paths)
    manifest = load_manifest(paths)
    ports = dict(manifest.get("ports") or {})
    payload = json.loads(paths.credentials.read_text(encoding="utf-8"))
    credentials = fixtures.Credentials(
        admin_name=payload["admin_name"],
        admin_password=payload["admin_password"],
        admin_token=payload["admin_token"],
        users=payload["users"],
    )
    container = JellyfinContainer(
        name=manifest["jellyfin"]["container"],
        run_id=manifest["run_id"],
        paths=paths,
        ports=ports,
        gateway=manifest["jellyfin"]["gateway"],
    )
    container.start()
    info = wait_for_jellyfin(container)
    if not str(info.get("Version", "")).startswith("12.3"):
        raise ValidationError(f"running Jellyfin is {info.get('Version')}, not the required 12.3")
    catalog = fixtures.item_catalog(container, credentials)

    ensure_directory(paths.webroot, 0o755)
    origin = MediaServer(paths.webroot, ports["media"], hosts=("127.0.0.1", container.gateway))
    origin.start()
    evidence_dir = ensure_directory(paths.evidence, 0o700)
    recorder = Recorder(evidence_dir / "supplement-checks.json")
    supervisor = ProcessSupervisor(paths)
    sessions: dict[str, Session] = {}
    direct_j = Session("J", container.base_url, credentials)
    ctx = Context(
        paths=paths,
        container=container,
        credentials=credentials,
        catalog=catalog,
        origin=origin,
        media_port=ports["media"],
    )
    started = utc_now()
    configs: dict[str, Any] = {}
    try:
        prepare_throttled_fixture(ctx, recorder)
        for group in groups:
            port = ports["proxy_b_on"] if group == "B-on" else ports["proxy_b_off"]
            plan = launch_proxy(
                supervisor,
                paths,
                group=group,
                port=port,
                upstream_url=container.base_url,
                cache_enabled=GROUP_CACHE[group],
                profile=PROFILE,
            )
            configs[group] = toml_dumps(plan.config)
            # The bypass check verifies the overlapping identity really is listed
            # in the global table as well, so the live config is attached here.
            ctx.proxy_config = dict(plan.config)
            sessions[group] = Session(group, f"http://127.0.0.1:{port}", credentials)
            print(
                f"-- group {group} port={port} cache={GROUP_CACHE[group]} "
                f"profile={PROFILE} upstream={container.base_url}",
                flush=True,
            )
            check_raw_unseeded(ctx, sessions[group], recorder, direct_j=direct_j)
            check_bypass_matrix(ctx, sessions[group], recorder, direct_j=direct_j)
            check_id_resolution(ctx, sessions[group], recorder)
            print("  second-id preservation cycle", flush=True)
            check_second_mapping_preserved(ctx, sessions[group], recorder, direct_j=direct_j)
            print("  stream abort / upstream release", flush=True)
            check_stream_abort_release(ctx, sessions[group], recorder, direct_j=direct_j)
            update_manifest(
                paths,
                proxy_processes=[
                    {
                        "group": group,
                        "pid": plan.process.pid,
                        "config": str(plan.config_path),
                    }
                ],
            )

        print("-- outage and recovery", flush=True)
        check_unreachable_and_recovery(ctx, sessions, direct_j, recorder)
    finally:
        supervisor.stop_all()
        origin.stop()
        for session in sessions.values():
            session.close()
        direct_j.close()
        update_manifest(paths, proxy_processes=[])

    summary = {
        "started_at": started,
        "finished_at": utc_now(),
        "groups": list(groups),
        "profile": PROFILE,
        "product_configs": configs,
        "jellyfin": {
            "container": container.name,
            "image_reference": manifest["jellyfin"]["image_reference"],
            "image_digest": manifest["jellyfin"]["image_digest"],
            "server_version": info.get("Version"),
            "server_id": info.get("Id"),
            "product_base": manifest["product_base"]["base_sha"],
        },
        "tool_identity": tool_identity(),
        "checks": len(recorder.checks),
        "failed": [check["id"] for check in recorder.failures],
        "ok": not recorder.failures,
    }
    write_json(evidence_dir / "supplement-summary.json", summary, mode=0o600)
    print(json.dumps({"checks": summary["checks"], "failed": summary["failed"]}, indent=1))
    return 0 if summary["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S1.1 functional supplement evidence (V1-V4)")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--groups", default="B-off,B-on")
    arguments = parser.parse_args(argv)
    groups = tuple(part.strip() for part in arguments.groups.split(",") if part.strip())
    unknown = [group for group in groups if group not in GROUP_CACHE]
    if unknown:
        raise ValidationError(f"unknown groups {unknown}; valid: {sorted(GROUP_CACHE)}")
    return run(arguments.run_dir, groups=groups)


if __name__ == "__main__":
    raise SystemExit(main())
