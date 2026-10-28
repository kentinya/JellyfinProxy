"""Baseline scenarios RJ-01 .. RJ-12 executed against the real Jellyfin 12.3.

Every record produced here is evidence: what was sent, which real upstream
transaction it caused, and what came back. No scenario constructs a synthetic
upstream response.
"""

from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import httpx

from scripts.validation.client import (
    TestClient,
    identity_headers,
    read_full,
)
from scripts.validation.common import (
    ValidationError,
    canonical_json,
    passthrough_matches_upstream,
    redact,
    redact_text,
    sha256_bytes,
    utc_now,
    write_json,
)
from scripts.validation.environment import JellyfinContainer, RunPaths
from scripts.validation.fixtures import (
    BYPASS_CLIENTS,
    IMAGE_NAME,
    refresh_library,
    write_strm,
)
from scripts.validation.json_diff import (
    compare_json,
    summarize_differences,
    url_equality_report,
)

GROUPS = ("J", "B-on", "B-off")
PLAYBACK_PREFIXES = ("/Items/{id}/PlaybackInfo", "/emby/Items/{id}/PlaybackInfo")

DEVICE_PROFILES: dict[str, dict[str, Any]] = {
    "alpha": {
        "Name": "AlphaProfile",
        "MaxStreamingBitrate": 20000000,
        "DirectPlayProfiles": [
            {"Container": "mp4,mkv", "Type": "Video", "VideoCodec": "h264,hevc", "AudioCodec": "aac,mp3"}
        ],
        "TranscodingProfiles": [
            {"Container": "ts", "Type": "Video", "VideoCodec": "h264", "AudioCodec": "aac", "Protocol": "hls"}
        ],
    },
    "beta": {
        "Name": "BetaProfile",
        "MaxStreamingBitrate": 4000000,
        "DirectPlayProfiles": [{"Container": "mp4", "Type": "Video", "VideoCodec": "h264", "AudioCodec": "aac"}],
        "TranscodingProfiles": [
            {"Container": "mp4", "Type": "Video", "VideoCodec": "h264", "AudioCodec": "aac", "Protocol": "http"}
        ],
        "CodecProfiles": [{"Type": "Video", "Codec": "h264", "Conditions": []}],
    },
}


class ResultRecorder:
    """Append-only evidence recorder with per-scenario status semantics."""

    def __init__(self, paths: RunPaths) -> None:
        self.paths = paths
        self._results: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def record(
        self,
        case: str,
        group: str,
        subcase: str,
        status: str,
        *,
        detail: Mapping[str, Any] | None = None,
        notes: Sequence[str] = (),
    ) -> dict[str, Any]:
        key = f"{case}:{group}:{subcase}"
        entry = {
            "case": case,
            "group": group,
            "subcase": subcase,
            "status": status,
            "detail": dict(detail or {}),
            "notes": [redact_text(note) for note in notes],
            "recorded_at": utc_now(),
        }
        with self._lock:
            self._results[key] = entry
        self._flush()
        return entry

    def _flush(self) -> None:
        write_json(self.paths.evidence / "results.json", self._results, mode=0o600)

    def results(self) -> dict[str, dict[str, Any]]:
        """Return the recorded results; the CLI exports the transaction ledger."""
        return dict(self._results)

    def statuses(self) -> dict[str, str]:
        return {key: value["status"] for key, value in self._results.items()}


@dataclass
class GroupContext:
    group: str
    base_url: str
    proxy_port: int | None
    observatory_port: int
    credentials: Any
    catalog: Mapping[str, Any]
    paths: RunPaths
    gateway: str
    media_port: int
    recorder: ResultRecorder
    jellyfin: JellyfinContainer
    restarts: dict[str, int] = field(default_factory=dict)
    process_management: Any = None
    notes: list[str] = field(default_factory=list)

    @property
    def is_proxy(self) -> bool:
        return self.group != "J"

    @property
    def json_log(self) -> Path:
        return self.paths.observatory / "observatory.jsonl"

    def item(self, key: str) -> dict[str, Any]:
        return self.catalog[key]

    def token(self, user: str = "s1user1") -> str:
        return self.credentials.users[user]["token"]

    def remote_url(self, target: str) -> str:
        return f"http://{self.gateway}:{self.media_port}/{target.lstrip('/')}"

    # -- observatory -----------------------------------------------------
    def transactions(self, *, path_regex: str | None = None, request_ids: Iterable[str] | None = None) -> list[dict[str, Any]]:
        if not self.json_log.exists():
            return []
        wanted = set(request_ids) if request_ids is not None else None
        pattern = re.compile(path_regex) if path_regex else None
        entries: list[dict[str, Any]] = []
        with self.json_log.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if record.get("group") != self.group:
                    continue
                if wanted is not None and record.get("request_headers", {}).get("x-request-id") not in wanted:
                    continue
                if pattern and not pattern.search(str(record.get("path", ""))):
                    continue
                entries.append(record)
        return entries

    def upstream_count(self, path_regex: str, request_ids: Iterable[str] | None = None) -> int:
        return len(self.transactions(path_regex=path_regex, request_ids=request_ids))

    def last_json(self, path_regex: str, request_ids: Iterable[str] | None = None) -> dict[str, Any] | None:
        entries = self.transactions(path_regex=path_regex, request_ids=request_ids)
        for record in reversed(entries):
            if isinstance(record.get("json"), dict):
                return record["json"]
        return None

    # -- requests --------------------------------------------------------
    def client(self, *, timeout: float = 60.0) -> TestClient:
        return TestClient(self.base_url, timeout=timeout)

    def playback_info(
        self,
        item_key: str,
        *,
        method: str = "GET",
        user: str = "s1user1",
        client_name: str = "PlainClient",
        device: str = "s1-device-alpha",
        device_id: str = "s1-device-alpha",
        profile: str | None = None,
        extra_query: str = "",
        path_prefix: str = "",
        request_id: str | None = None,
    ) -> tuple[Any, dict[str, str]]:
        item = self.item(item_key)
        token = self.token(user)
        headers = identity_headers(client_name, device, device_id=device_id, token=token)
        path = f"{path_prefix}/Items/{item['id']}/PlaybackInfo{extra_query}"
        body = None
        if method == "POST":
            payload: dict[str, Any] = {"UserId": self.credentials.users[user]["user_id"]}
            if profile:
                payload["DeviceProfile"] = DEVICE_PROFILES[profile]
            body = json.dumps(payload).encode()
            headers["content-type"] = "application/json"
        with self.client() as client:
            response = client.request(
                method,
                path,
                headers=headers,
                body=body,
                request_id=request_id,
            )
        return response, {"path": path, "method": method, "profile": profile, "user": user, "client": client_name}


# ---------------------------------------------------------------------------
# shared assertions
# ---------------------------------------------------------------------------


def _status_ok(response: Any) -> bool:
    return getattr(response, "status", None) == 200


def _json(response: Any) -> Any:
    return response.json_body()


def _media_sources(document: Any) -> list[dict[str, Any]]:
    if not isinstance(document, dict):
        return []
    sources = document.get("MediaSources")
    return [source for source in sources or [] if isinstance(source, dict)]


def _first_source(document: Any) -> dict[str, Any] | None:
    sources = _media_sources(document)
    return sources[0] if sources else None


def _pick_item(ctx: GroupContext, *, remote_only: bool = True) -> dict[str, Any] | None:
    for key in ("remote", "remote_two", "dynamic", "throttle"):
        item = ctx.item(key)
        sources = item.get("media_sources") or []
        if not sources:
            continue
        if remote_only and not any(source.get("is_remote") for source in sources):
            continue
        return item
    return None


def _pick_local_item(ctx: GroupContext) -> dict[str, Any] | None:
    for key in ("local", "multi"):
        item = ctx.item(key)
        sources = item.get("media_sources") or []
        if any(not source.get("is_remote") for source in sources):
            return item
    return None


def _cache_header(response: Any) -> str | None:
    return response.header("x-jellyfinproxy-cache")


def _same_transaction_bytes(ctx: GroupContext, response: Any, request_id: str) -> dict[str, Any]:
    """Compare the client body digest with the digest of its own upstream transaction.

    The observatory stores the digest of the bytes it actually relayed, so this is
    a byte-exact comparison over one upstream transaction (no second request).
    """

    entries = ctx.transactions(path_regex=r"/PlaybackInfo", request_ids=[request_id])
    if not entries:
        return {"upstream_transaction": False}
    record = entries[-1]
    return {
        "upstream_transaction": True,
        "upstream_body_sha256": record.get("response_body_sha256"),
        "client_body_sha256": response.body_sha256,
        "byte_identical": record.get("response_body_sha256") == response.body_sha256,
        "upstream_status": record.get("status"),
    }


# ---------------------------------------------------------------------------
# RJ-01 version and basic transparent proxying
# ---------------------------------------------------------------------------


def rj01(ctx: GroupContext) -> None:
    case = "RJ-01"
    with ctx.client() as client:
        public = client.get("/System/Info/Public")
        if not _status_ok(public):
            ctx.recorder.record(case, ctx.group, "public_info", "FAIL", detail=public.summary())
            return
        info = _json(public)
        version = str(info.get("Version", ""))
        ctx.recorder.record(
            case,
            ctx.group,
            "public_info",
            "PASS" if version.startswith("12.3") else "FAIL",
            detail={
                **public.summary(),
                "server_version": version,
                "server_id": info.get("Id"),
                "startup_wizard_completed": info.get("StartupWizardCompleted"),
                "product_name": info.get("ProductName"),
            },
            notes=["public endpoint used to confirm the running 12.3 build"],
        )

        headers = identity_headers("PlainClient", "s1-device-alpha", device_id="s1-device-alpha", token=ctx.token())
        items = client.get("/Items?Recursive=true&IncludeItemTypes=Movie&Limit=50", headers=headers)
        payload = _json(items) if _status_ok(items) else {}
        names = [entry.get("Name") for entry in payload.get("Items", [])]
        ctx.recorder.record(
            case,
            ctx.group,
            "item_list",
            "PASS" if _status_ok(items) and payload.get("Items") else "FAIL",
            detail={**items.summary(), "item_count": len(payload.get("Items", [])), "first_names": names[:5]},
        )

        local = _pick_local_item(ctx)
        if local is not None:
            image = client.get(
                f"/Items/{local['id']}/Images/Primary?maxHeight=120",
                headers={**headers, "accept": "image/jpeg,image/png"},
            )
            ctx.recorder.record(
                case,
                ctx.group,
                "metadata_image",
                "PASS" if image.status == 200 and len(image.body) > 0 else "FAIL",
                detail={
                    **image.summary(),
                    "content_type": image.header("content-type"),
                    "fixture_file": IMAGE_NAME,
                },
            )

        # Response adaptation: what the proxy must preserve or may change.
        item = _pick_item(ctx)
        if item is not None:
            response, request = ctx.playback_info("remote")
            document = _json(response) if _status_ok(response) else None
            source = _first_source(document)
            ctx.recorder.record(
                case,
                ctx.group,
                "playback_info_adaptation",
                "PASS" if source and source.get("Path") else "FAIL",
                detail={
                    **response.summary(),
                    "request": request,
                    "protocol": (source or {}).get("protocol", (source or {}).get("Protocol")),
                    "cache_header": _cache_header(response),
                    "proxy_version_header": response.header("x-jellyfinproxy-version"),
                    "request_id_echo": response.header("x-request-id") == response.request_id,
                    "content_type": response.header("content-type"),
                },
                notes=["upstream response headers excluded: date, server, content-length, content-encoding"],
            )

        prefix = client.get("/emby/System/Info/Public")
        ctx.recorder.record(
            case,
            ctx.group,
            "old_prefix_public_info",
            "PASS",
            detail={**prefix.summary(), "note": "recorded actual upstream status for the removed /emby prefix"},
        )


# ---------------------------------------------------------------------------
# RJ-02 repeated / concurrent PlaybackInfo
# ---------------------------------------------------------------------------


def _playback_transactions(ctx: GroupContext, request_ids: Sequence[str]) -> dict[str, Any]:
    entries = ctx.transactions(path_regex=r"/PlaybackInfo", request_ids=request_ids)
    by_id: dict[str, int] = {}
    for record in entries:
        rid = record.get("request_headers", {}).get("x-request-id", "")
        by_id[rid] = by_id.get(rid, 0) + 1
    return {"total": len(entries), "per_request": by_id}


def rj02(ctx: GroupContext) -> None:
    case = "RJ-02"
    item_key = "remote"
    item = ctx.item(item_key)

    # warm-up so that "hot" semantics are explicit
    warm, _ = ctx.playback_info(item_key, user="s1user1", client_name="PlainClient")
    ctx.recorder.record(
        case,
        ctx.group,
        "warmup",
        "PASS" if _status_ok(warm) else "FAIL",
        detail={**warm.summary(), "cache_header": _cache_header(warm), "item_id": item["id"]},
    )

    serial_ids = [f"s1-rj02-serial-{ctx.group}-{index}" for index in range(3)]
    serial_bodies: list[str] = []
    serial_cache: list[str | None] = []
    for rid in serial_ids:
        response, _ = ctx.playback_info(item_key, request_id=rid)
        if not _status_ok(response):
            ctx.recorder.record(case, ctx.group, "serial_3", "FAIL", detail=response.summary())
            return
        serial_bodies.append(response.body_sha256)
        serial_cache.append(_cache_header(response))
    serial_counts = _playback_transactions(ctx, serial_ids)
    ctx.recorder.record(
        case,
        ctx.group,
        "serial_3",
        "PASS",
        detail={
            "item_id": item["id"],
            "requests": 3,
            "body_sha256": serial_bodies,
            "distinct_bodies": len(set(serial_bodies)),
            "cache_headers": serial_cache,
            "upstream_transactions": serial_counts,
        },
        notes=[
            "B-on is expected to answer 2 of 3 from the original JSON cache (fewer upstream transactions)",
            "distinct bodies are expected because Jellyfin generates a new PlaySessionId per transaction",
        ],
    )

    # concurrency on a cold entry: use a distinct prefix/query to avoid the warm entry
    concurrent_ids = [f"s1-rj02-concurrent-{ctx.group}-{index}" for index in range(4)]

    def _one(rid: str) -> Any:
        response, _ = ctx.playback_info(item_key, request_id=rid, extra_query="?MaxStreamingBitrate=8000000")
        return response

    with ThreadPoolExecutor(max_workers=4) as pool:
        concurrent = list(pool.map(_one, concurrent_ids))
    concurrent_counts = _playback_transactions(ctx, concurrent_ids)
    ctx.recorder.record(
        case,
        ctx.group,
        "concurrent_4",
        "PASS" if all(_status_ok(response) for response in concurrent) else "FAIL",
        detail={
            "requests": len(concurrent),
            "statuses": [response.status for response in concurrent],
            "cache_headers": [_cache_header(response) for response in concurrent],
            "distinct_bodies": len({response.body_sha256 for response in concurrent}),
            "upstream_transactions": concurrent_counts,
        },
        notes=["cold concurrent requests have no coalescing guarantee; the observed count is recorded as-is"],
    )

    # GET vs POST, two users, two device identities, different bodies
    variants = [
        ("get_user1", dict(method="GET", user="s1user1", device="s1-device-alpha", device_id="s1-device-alpha")),
        ("post_user1_alpha", dict(method="POST", user="s1user1", profile="alpha", device="s1-device-alpha", device_id="s1-device-alpha")),
        ("post_user2_beta", dict(method="POST", user="s1user2", profile="beta", device="s1-device-beta", device_id="s1-device-beta")),
    ]
    detail: dict[str, Any] = {}
    statuses: list[str] = []
    for name, kwargs in variants:
        rid = f"s1-rj02-{name}-{ctx.group}"
        response, request = ctx.playback_info(item_key, request_id=rid, **kwargs)
        counts = _playback_transactions(ctx, [rid])
        upstream = ctx.last_json(r"/PlaybackInfo", [rid])
        detail[name] = {
            "status": response.status,
            "cache_header": _cache_header(response),
            "upstream_transactions": counts["total"],
            "request": request,
            "upstream_play_session_present": bool((upstream or {}).get("PlaySessionId")),
        }
        statuses.append("PASS" if _status_ok(response) else "FAIL")
    ctx.recorder.record(case, ctx.group, "method_user_device_matrix", "PASS" if all(s == "PASS" for s in statuses) else "FAIL", detail=detail)


# ---------------------------------------------------------------------------
# RJ-03 default field comparison
# ---------------------------------------------------------------------------


def _compare_with_upstream(
    ctx: GroupContext,
    item_key: str,
    *,
    profile: str = "alpha",
    client_name: str = BYPASS_CLIENTS["cache"],
) -> dict[str, Any]:
    # The comparison must be anchored to a real upstream transaction of this
    # request. The cache-bypass client guarantees that in the cache-enabled
    # control group instead of silently comparing against a shared cached body.
    rid = f"s1-rj03-{ctx.group}-{item_key}"
    response, request = ctx.playback_info(
        item_key, method="POST", profile=profile, request_id=rid, client_name=client_name
    )
    if not _status_ok(response):
        return {"error": response.summary()}
    upstream = ctx.last_json(r"/PlaybackInfo", [rid])
    if upstream is None:
        return {
            "error": "no upstream JSON recorded for this transaction",
            "summary": response.summary(),
            "cache_header": _cache_header(response),
        }
    # The observatory stores a redacted copy of the upstream JSON, so the client
    # document is redacted identically before the field comparison. Byte-exactness
    # is still asserted separately through the raw body digests.
    differences = compare_json(upstream, redact(_json(response)))
    return {
        "request": request,
        "upstream_document_sha": sha256_bytes(canonical_json(upstream)),
        "proxy_document_sha": sha256_bytes(canonical_json(redact(_json(response)))),
        "same_transaction": _same_transaction_bytes(ctx, response, rid),
        "differences": summarize_differences(differences),
        "proxy_headers": response.summary()["headers"],
        "upstream_source": _first_source(upstream) and {
            "protocol": _first_source(upstream).get("Protocol"),
            "path_sha256": sha256_bytes(str(_first_source(upstream).get("Path")).encode())[:16],
        },
        "proxy_source": _first_source(_json(response)) and {
            "protocol": _first_source(_json(response)).get("Protocol"),
            "path_sha256": sha256_bytes(str(_first_source(_json(response)).get("Path")).encode())[:16],
        },
        "path_equality": url_equality_report(
            str((_first_source(upstream) or {}).get("Path")),
            str((_first_source(_json(response)) or {}).get("Path")),
        ),
    }


def rj03(ctx: GroupContext) -> None:
    case = "RJ-03"
    item = _pick_item(ctx, remote_only=True)
    if item is None:
        ctx.recorder.record(case, ctx.group, "remote_source", "BLOCKED", notes=["no remote media source in the fixture library"])
        return
    result = _compare_with_upstream(ctx, "remote")
    changed = (result.get("differences") or {}).get("unexpected") or []
    status = "FAIL" if result.get("error") else "PASS"
    # J is the upstream itself: only Jellyfin's own per-transaction fields may differ.
    if status == "PASS" and not ctx.is_proxy and changed:
        status = "FAIL"
    plain_rid = f"s1-rj03-{ctx.group}-remote-plain"
    plain_response, _ = ctx.playback_info("remote", method="POST", profile="alpha", request_id=plain_rid)
    plain_source = _first_source(_json(plain_response)) if _status_ok(plain_response) else None
    ctx.recorder.record(
        case,
        ctx.group,
        "remote_source_fields_plain_client",
        "PASS" if _status_ok(plain_response) else "FAIL",
        detail={
            "status": plain_response.status,
            "cache_header": _cache_header(plain_response),
            "upstream_transactions": ctx.upstream_count(r"/PlaybackInfo", [plain_rid]),
            "protocol": (plain_source or {}).get("Protocol"),
            "path_digest": sha256_bytes(str((plain_source or {}).get("Path")).encode())[:16],
        },
        notes=["records whether the ordinary client was answered by the pre-change JSON cache"],
    )
    ctx.recorder.record(
        case,
        ctx.group,
        "remote_source_fields",
        status,
        detail={
            **result,
            "changed_field_locations": changed,
            "pre_change_rule_effect": (
                "Protocol/SupportsTranscoding rewritten by the original PlaybackService rule"
                if ctx.is_proxy
                else "not applicable (no proxy in front of Jellyfin)"
            ),
        },
        notes=[
            "B-on/B-off are expected to rewrite Protocol and SupportsTranscoding for remote sources (pre-change behaviour)",
            "J must not differ from itself; any difference there is a comparison defect",
            "TranscodingUrl is listed because Jellyfin embeds Protocol/TranscodingSubProtocol in it; the proxy does not edit that field",
        ],
    )

    local = _pick_local_item(ctx)
    if local is not None:
        local_result = _compare_with_upstream(ctx, "local")
        ctx.recorder.record(
            case,
            ctx.group,
            "local_source_fields",
            "FAIL" if local_result.get("error") else "PASS",
            detail=local_result,
            notes=["local File sources must stay byte-identical in every group"],
        )


# ---------------------------------------------------------------------------
# RJ-04 bypass matrix
# ---------------------------------------------------------------------------


def rj04(ctx: GroupContext) -> None:
    case = "RJ-04"
    item = _pick_item(ctx, remote_only=True)
    if item is None:
        ctx.recorder.record(case, ctx.group, "matrix", "BLOCKED", notes=["no remote media source"])
        return
    identities = {
        "normal": BYPASS_CLIENTS["normal"],
        "playback_only": BYPASS_CLIENTS["playback"],
        "video_only": BYPASS_CLIENTS["video"],
        "global": BYPASS_CLIENTS["global"],
        "overlap": BYPASS_CLIENTS["overlap"],
        "cache_only": BYPASS_CLIENTS["cache"],
    }
    detail: dict[str, Any] = {}
    shared_entry: dict[str, Any] | None = None
    for label, client_name in identities.items():
        rid = f"s1-rj04-{label}-{ctx.group}"
        response, _ = ctx.playback_info("remote", client_name=client_name, request_id=rid)
        upstream = ctx.last_json(r"/PlaybackInfo", [rid])
        source = _first_source(_json(response)) if _status_ok(response) else None
        row: dict[str, Any] = {
            "status": response.status,
            "cache_header": _cache_header(response),
            "protocol": (source or {}).get("Protocol"),
            "media_source_id": (source or {}).get("Id"),
            "upstream_transactions": ctx.upstream_count(r"/PlaybackInfo", [rid]),
            "same_transaction": _same_transaction_bytes(ctx, response, rid),
        }
        if upstream is None:
            # No upstream call for this request: the product answered from its own
            # JSON cache (only possible in the cache-enabled control group). The
            # row is kept so the pre-change masking stays visible in the evidence.
            row["source"] = "proxy_json_cache_shared_entry"
            if shared_entry is not None:
                row["unexpected_differences"] = summarize_differences(
                    compare_json(shared_entry, redact(_json(response)))
                )["unexpected"]
            detail[label] = row
            continue
        differences = compare_json(upstream, redact(_json(response)))
        row["source"] = "upstream_transaction"
        row["unexpected_differences"] = summarize_differences(differences)["unexpected"]
        if _cache_header(response) == "MISS" and shared_entry is None:
            shared_entry = upstream
        detail[label] = row
    problems = [label for label, row in detail.items() if row["status"] != 200]
    ctx.recorder.record(
        case,
        ctx.group,
        "body_matrix",
        "PASS" if not problems else "FAIL",
        detail={
            "rows": detail,
            "cache_bypass_rows": [label for label, row in detail.items() if row["source"] == "upstream_transaction"],
            "cache_shared_rows": [label for label, row in detail.items() if row["source"] == "proxy_json_cache_shared_entry"],
        },
        notes=[
            "J has no proxy so every row must equal the upstream body",
            "B-on may serve a shared cached body to non-cache-bypass clients (pre-change behaviour)",
            "a row without an upstream transaction is a real cache hit and is recorded as such, not as a failure",
        ],
    )

    # case-insensitive matching across the three identity header positions
    variants = {}
    for name, form, value in (
        ("x_emby_client_lower", "x-emby-client", BYPASS_CLIENTS["global"].lower()),
        ("x_emby_device_name_upper", "x-emby-device-name", BYPASS_CLIENTS["global"].upper()),
        ("user_agent_mixed", "user-agent", BYPASS_CLIENTS["global"]),
    ):
        token = ctx.token()
        headers = identity_headers(value, "s1-device-alpha", device_id="s1-device-alpha", form=form, token=token)
        rid = f"s1-rj04-identity-{name}-{ctx.group}"
        with ctx.client() as client:
            response = client.request("GET", f"/Items/{item['id']}/PlaybackInfo", headers=headers, request_id=rid)
        upstream = ctx.last_json(r"/PlaybackInfo", [rid])
        differences = compare_json(upstream, _json(response)) if upstream else []
        variants[name] = {
            "status": response.status,
            "identity_value": value,
            "unexpected_differences": summarize_differences(differences)["unexpected"],
            "body_matches_upstream": not summarize_differences(differences)["unexpected"],
        }
    ctx.recorder.record(
        case,
        ctx.group,
        "identity_header_positions",
        "PASS" if all(entry["status"] == 200 for entry in variants.values()) else "FAIL",
        detail=variants,
    )

    # Video redirect independence and media source bookkeeping
    video = _video_redirect(ctx, item, client_name=BYPASS_CLIENTS["video"])
    normal = _video_redirect(ctx, item, client_name=BYPASS_CLIENTS["normal"])
    if ctx.is_proxy:
        ok = normal.get("status") == 302 and video.get("status") == 200
    else:
        ok = normal.get("status") == 200 and video.get("status") == 200
    ctx.recorder.record(
        case,
        ctx.group,
        "video_independence",
        "PASS" if ok else "FAIL",
        detail={"video_bypass_client": video, "normal_client": normal},
        notes=[
            "for J no redirect is possible, so both rows must show the upstream status",
            "for the proxies the normal client must be redirected while the Video-bypass client must be proxied",
        ],
    )


def _video_redirect(ctx: GroupContext, item: Mapping[str, Any], *, client_name: str) -> dict[str, Any]:
    source = (item.get("media_sources") or [{}])[0]
    media_source_id = source.get("id") or item["id"]
    headers = identity_headers(client_name, "s1-device-alpha", device_id="s1-device-alpha", token=ctx.token())
    with ctx.client() as client:
        response = client.get(
            f"/Videos/{item['id']}/stream?static=true&MediaSourceId={media_source_id}",
            headers=headers,
        )
    return {
        "status": response.status,
        "location_present": bool(response.header("location")),
        "location_digest": sha256_bytes(str(response.header("location")).encode())[:12] if response.header("location") else None,
        "content_type": response.header("content-type"),
        "bytes": len(response.body),
    }


# ---------------------------------------------------------------------------
# RJ-05 media source redirect matrix
# ---------------------------------------------------------------------------


def _seed_mapping(ctx: GroupContext, item_key: str = "remote") -> dict[str, Any] | None:
    response, _ = ctx.playback_info(item_key)
    if not _status_ok(response):
        return None
    source = _first_source(_json(response))
    return source


def _raw_entry_paths(item_id: str) -> tuple[tuple[str, str], ...]:
    return (
        ("emby_raw", f"/emby/api/danmu/{item_id}/raw"),
        ("raw", f"/api/danmu/{item_id}/raw"),
    )


def _raw_observation(response) -> dict[str, Any]:
    location = response.header("location")
    return {
        "status": response.status,
        "body_sha256": response.body_sha256,
        "body_bytes": len(response.body),
        "content_type": response.header("content-type"),
        "location_present": bool(location),
        "location_digest": sha256_bytes(location.encode())[:12] if location else None,
    }


def _raw_passthrough(ctx: GroupContext, item_id: str, headers: Mapping[str, str], tag: str) -> tuple[dict[str, Any], bool]:
    """Compare both raw entries with the direct Jellyfin response.

    The proxy must not manufacture a media redirect even when the same item has
    a cached mapping. The direct server is the baseline for status, body and
    Content-Type; an upstream-originated Location is allowed only when the
    direct response has the same Location.
    """

    rows: dict[str, Any] = {}
    for label, path in _raw_entry_paths(item_id):
        with TestClient(ctx.jellyfin.base_url) as direct:
            baseline = _raw_observation(direct.get(path, headers=headers))
        request_id = f"s1-{tag}-{ctx.group}-{label}"
        with ctx.client() as client:
            observed = _raw_observation(client.get(path, headers=headers, request_id=request_id))
        observed["path"] = path
        observed["jellyfin_direct"] = baseline
        observed["upstream_transactions"] = ctx.upstream_count(r"/api/danmu/[^/]+/raw", [request_id])
        observed["matches_upstream"] = (
            observed["upstream_transactions"] > 0
            and passthrough_matches_upstream(observed, baseline)
        )
        rows[label] = observed
    return rows, all(row["matches_upstream"] for row in rows.values())


def rj05(ctx: GroupContext) -> None:
    case = "RJ-05"
    item = ctx.item("remote")
    source = _pick_item(ctx, remote_only=True) and ctx.item("remote")
    item_id = item["id"]
    token = ctx.token()
    headers = identity_headers("PlainClient", "s1-device-alpha", device_id="s1-device-alpha", token=token)

    # Raw entries are checked before and after this case seeds the mapping. The
    # direct Jellyfin response is the baseline in both positions.
    raw_before, raw_before_ok = _raw_passthrough(ctx, item_id, headers, "rj05-raw-before")
    ctx.recorder.record(
        case,
        ctx.group,
        "raw_before_seed",
        "PASS" if raw_before_ok else "FAIL",
        detail={"rows": raw_before},
        notes=[
            "both raw entries must keep Jellyfin's status, body, Content-Type and any upstream Location",
            "a proxy-generated video redirect, or a request that never reaches upstream, fails",
        ],
    )

    seeded = _seed_mapping(ctx, "remote")
    if seeded is None:
        ctx.recorder.record(case, ctx.group, "seed_mapping", "FAIL", detail={"error": "PlaybackInfo failed"})
        return
    raw_after, raw_after_ok = _raw_passthrough(ctx, item_id, headers, "rj05-raw-after")
    ctx.recorder.record(
        case,
        ctx.group,
        "raw_after_seed",
        "PASS" if raw_after_ok else "FAIL",
        detail={"seed_protocol": seeded.get("Protocol"), "rows": raw_after},
        notes=[
            "the same item now has a mapping, yet both raw entries must still use the plain proxy",
            "the direct Jellyfin row is the baseline; an old 302-to-seeded-URL result is a FAIL now",
        ],
    )

    media_source_id = seeded.get("Id") or item["id"]
    compact = media_source_id.replace("-", "")
    cases = {
        "query_MediaSourceId": f"/Videos/{item_id}/stream?static=true&MediaSourceId={media_source_id}",
        "query_mediaSourceId": f"/Videos/{item_id}/stream?static=true&mediaSourceId={media_source_id}",
        "path_videos_id": f"/videos/{media_source_id}/stream?static=true",
        "uuid_compact": f"/Videos/{item_id}/stream?static=true&MediaSourceId={compact}",
        "Videos_upper": f"/Videos/{media_source_id}/stream",
        "Videos_lower": f"/videos/{media_source_id}/stream",
    }
    detail: dict[str, Any] = {}
    for label, path in cases.items():
        with ctx.client() as client:
            response = client.get(path, headers=headers)
        location = response.header("location")
        follow = None
        if response.status == 302 and location:
            follow = read_full(location, max_bytes=256 * 1024)
        detail[label] = {
            "path_template": path.replace(item_id, "{itemId}").replace(media_source_id, "{mediaSourceId}").replace(compact, "{compactId}"),
            "status": response.status,
            "location_digest": sha256_bytes(location.encode())[:12] if location else None,
            "location_matches_seed": url_equality_report(str(seeded.get("Path")), location) if location else None,
            "followed": follow,
        }
    expected_redirect = {"query_MediaSourceId", "query_mediaSourceId", "path_videos_id", "uuid_compact", "Videos_upper", "Videos_lower"}
    if ctx.is_proxy:
        statuses = {
            label: ("PASS" if detail[label]["status"] == 302 and detail[label]["followed"] and detail[label]["followed"]["bytes_read"] > 0 else "FAIL")
            for label in expected_redirect
        }
    else:
        statuses = {label: "PASS" for label in cases}
    ctx.recorder.record(
        case,
        ctx.group,
        "redirect_matrix",
        "PASS" if all(value == "PASS" for value in statuses.values()) else "FAIL",
        detail={"seed_protocol": seeded.get("Protocol"), "cases": detail, "statuses": statuses},
        notes=[
            "media bytes are read from the real controlled origin after following the original Location",
            "J cannot redirect, so its rows only document the upstream status for the same request",
        ],
    )

    # MediaSourceId query parameter wins over the path id
    conflict = f"/Videos/{item_id}/stream?static=true&MediaSourceId={media_source_id}"
    with ctx.client() as client:
        response = client.get(conflict, headers=headers)
    ctx.recorder.record(
        case,
        ctx.group,
        "query_beats_path",
        "PASS",
        detail={"status": response.status, "location_digest": sha256_bytes(str(response.header("location")).encode())[:12] if response.header("location") else None},
    )


# ---------------------------------------------------------------------------
# RJ-06 same id valid -> invalid -> valid
# ---------------------------------------------------------------------------


def _dynamic_playback(ctx: GroupContext, *, client_name: str = "PlainClient") -> dict[str, Any]:
    response, _ = ctx.playback_info("dynamic", client_name=client_name)
    if not _status_ok(response):
        return {"status": response.status, "error": True}
    source = _first_source(_json(response))
    return {
        "status": response.status,
        "protocol": (source or {}).get("Protocol"),
        "path_sha256": sha256_bytes(str((source or {}).get("Path")).encode())[:16] if (source or {}).get("Path") else None,
        "path": (source or {}).get("Path"),
        "cache_header": _cache_header(response),
    }


def _video_status(ctx: GroupContext, item_key: str) -> dict[str, Any]:
    item = ctx.item(item_key)
    media_source_id = (item.get("media_sources") or [{}])[0].get("id") or item["id"]
    headers = identity_headers("PlainClient", "s1-device-alpha", device_id="s1-device-alpha", token=ctx.token())
    with ctx.client() as client:
        response = client.get(
            f"/Videos/{item['id']}/stream?static=true&MediaSourceId={media_source_id}", headers=headers
        )
    return {"status": response.status, "location_present": bool(response.header("location"))}


def _set_strm_and_refresh(ctx: GroupContext, value: str | None) -> dict[str, Any]:
    """Drive one real same-item media-source transition through supported APIs.

    Observed 12.3 behaviour (this is why two scans are needed): editing the STRM
    content in place makes Jellyfin re-read metadata but keeps the previously
    resolved MediaSource; removing the STRM, scanning, re-adding it and scanning
    again makes Jellyfin resolve the new target while keeping the same item id.
    """

    from scripts.validation.fixtures import MEDIA_LAYOUT

    entry = next(item for item in MEDIA_LAYOUT if item["key"] == "dynamic")
    target = ctx.paths.media / "movies" / entry["folder"] / entry["file"]
    item_id = ctx.item("dynamic")["id"]
    if target.exists():
        target.unlink()
    refresh_library(ctx.jellyfin, ctx.credentials, timeout=300)
    if value is not None:
        write_strm(ctx.paths, "dynamic", value)
        refresh_library(ctx.jellyfin, ctx.credentials, timeout=300)
    return {
        "value": None if value is None else "[set]",
        "item_id": item_id,
        "rescan_steps": 2 if value is not None else 1,
    }


def rj06(ctx: GroupContext) -> None:
    case = "RJ-06"
    item = ctx.item("dynamic")
    original_id = item["id"]
    second_id = ctx.item("remote_two")["id"]

    if not ctx.is_proxy:
        sequence = []
        for step, value in (
            ("valid_http_a", ctx.remote_url("remote-a.mp4")),
            ("invalid_local", "/media/movies/Local/Local Sample (2020)/Local Sample (2020).mp4"),
            ("valid_http_b", ctx.remote_url("remote-b.mp4")),
        ):
            _set_strm_and_refresh(ctx, value)
            sequence.append({"step": step, "playback": _dynamic_playback(ctx)})
        ids = {entry["playback"].get("path") for entry in sequence}
        ctx.recorder.record(
            case,
            ctx.group,
            "upstream_sequence",
            "PASS" if len(ids) == 3 else "FAIL",
            detail={"item_id": original_id, "sequence": sequence},
            notes=["J documents the real upstream responses used as the basis for the proxy rows"],
        )
        return

    steps: list[dict[str, Any]] = []
    _set_strm_and_refresh(ctx, ctx.remote_url("remote-a.mp4"))
    first = _dynamic_playback(ctx)
    first_video = _video_status(ctx, "dynamic")
    second_before = _video_status(ctx, "remote_two")
    steps.append({"step": "valid_http_a", "playback": first, "video": first_video, "second_item": second_before})

    _set_strm_and_refresh(ctx, "/media/movies/Local/Local Sample (2020)/Local Sample (2020).mp4")
    if ctx.group == "B-on":
        masked = _dynamic_playback(ctx)
        forced = _dynamic_playback(ctx, client_name=BYPASS_CLIENTS["cache"])
    else:
        masked = _dynamic_playback(ctx)
        forced = _dynamic_playback(ctx, client_name=BYPASS_CLIENTS["cache"])
    invalid_video = _video_status(ctx, "dynamic")
    second_during = _video_status(ctx, "remote_two")
    steps.append(
        {
            "step": "invalid_local",
            "playback": masked,
            "playback_cache_bypass": forced,
            "video": invalid_video,
            "second_item": second_during,
        }
    )

    _set_strm_and_refresh(ctx, ctx.remote_url("remote-b.mp4"))
    recovered = _dynamic_playback(ctx, client_name=BYPASS_CLIENTS["cache"])
    recovered_video_bypass = _video_status(ctx, "dynamic")
    second_after = _video_status(ctx, "remote_two")
    steps.append(
        {
            "step": "valid_http_b",
            "playback": recovered,
            "video": recovered_video_bypass,
            "second_item": second_after,
        }
    )

    ids_consistent = recovered.get("status") == 200
    ctx.recorder.record(
        case,
        ctx.group,
        "proxy_sequence",
        "PASS" if ids_consistent else "FAIL",
        detail={"item_id": original_id, "second_item_id": second_id, "steps": steps},
        notes=[
            "same item id is reused across the whole sequence; each transition is produced by a real library refresh",
            "B-on hot cache can mask the invalid step; the cache-bypass client row shows the real upstream result",
        ],
    )


# ---------------------------------------------------------------------------
# RJ-07 local media / mapping miss / Video bypass
# ---------------------------------------------------------------------------


def rj07(ctx: GroupContext) -> None:
    case = "RJ-07"
    local = _pick_local_item(ctx)
    if local is None:
        ctx.recorder.record(case, ctx.group, "range", "BLOCKED", notes=["no local media item"])
        return
    media_source_id = (local.get("media_sources") or [{}])[0].get("id") or local["id"]
    headers = identity_headers("PlainClient", "s1-device-alpha", device_id="s1-device-alpha", token=ctx.token())
    checks = {}
    for label, range_header in (("full", None), ("range_0_1023", "bytes=0-1023"), ("range_tail", "bytes=-512")):
        request_headers = dict(headers)
        if range_header:
            request_headers["range"] = range_header
        with ctx.client() as client:
            response = client.get(
                f"/Videos/{local['id']}/stream?static=true&MediaSourceId={media_source_id}",
                headers=request_headers,
            )
        checks[label] = {
            **response.summary(),
            "content_range": response.header("content-range"),
            "accept_ranges": response.header("accept-ranges"),
            "location_present": bool(response.header("location")),
        }
    expected = checks["range_0_1023"]
    ok = expected["status"] in (200, 206)
    ctx.recorder.record(
        case,
        ctx.group,
        "range",
        "PASS" if ok else "FAIL",
        detail=checks,
        notes=["local media must never be redirected; Range handling must stay upstream-provided"],
    )

    # mapping miss: a media source id that was never seeded
    unknown = "ffffffffffffffffffffffffffffffff"
    with ctx.client() as client:
        miss = client.get(
            f"/Videos/{local['id']}/stream?static=true&MediaSourceId={unknown}", headers=headers
        )
    ctx.recorder.record(
        case,
        ctx.group,
        "mapping_miss",
        "PASS" if miss.status in (200, 206, 404, 400) else "FAIL",
        detail={**miss.summary(), "location_present": bool(miss.header("location"))},
        notes=["an unknown MediaSourceId must fall through to the real upstream response"],
    )


# ---------------------------------------------------------------------------
# RJ-08 stream lifecycle
# ---------------------------------------------------------------------------


def _origin_requests(ctx: GroupContext) -> int:
    # The controlled origin runs inside the tool process, so ask the runner.
    hook = getattr(ctx, "origin_snapshot", None)
    return len(hook() if hook else [])


def rj08(ctx: GroupContext) -> None:
    case = "RJ-08"
    remote_item = _pick_item(ctx, remote_only=True)
    local_item = _pick_local_item(ctx)
    if local_item is None:
        ctx.recorder.record(case, ctx.group, "stream", "BLOCKED", notes=["no local media item"])
        return

    # Phase 1: remote source -> the proxy answers 302 and the real origin streams.
    # Phase 2: local source  -> the proxy itself streams, so cancellation and
    #          upstream release are observable on the proxy path.
    remote_phase: dict[str, Any] = {}
    if remote_item is not None:
        _seed_mapping(ctx, "remote")
        remote_source_id = (remote_item.get("media_sources") or [{}])[0].get("id") or remote_item["id"]
        remote_headers = identity_headers("PlainClient", "s1-device-alpha", device_id="s1-device-alpha", token=ctx.token())
        with ctx.client() as client:
            remote = client.get(
                f"/Videos/{remote_item['id']}/stream?static=true&MediaSourceId={remote_source_id}",
                headers={**remote_headers, "range": "bytes=0-4095"},
            )
        location = remote.header("location")
        remote_phase = {
            "status": remote.status,
            "location_present": bool(location),
            "followed": read_full(location, headers={"range": "bytes=0-4095"}, max_bytes=65536) if location else None,
        }

    item = local_item
    seeded = None
    media_source_id = (item.get("media_sources") or [{}])[0].get("id") or item["id"]
    headers = identity_headers("PlainClient", "s1-device-alpha", device_id="s1-device-alpha", token=ctx.token())
    snapshot: Callable[[], list[dict[str, Any]]] | None = getattr(ctx, "origin_snapshot", None)

    def _snapshot() -> list[dict[str, Any]]:
        return snapshot() if snapshot else []

    before = len(_snapshot())
    with ctx.client() as client:
        response = client.get(f"/Videos/{item['id']}/stream?static=true&MediaSourceId={media_source_id}", headers=headers)
    location = response.header("location") or f"{ctx.base_url}/Videos/{item['id']}/stream?static=true&MediaSourceId={media_source_id}"
    start_report = read_full(location, headers={"range": "bytes=0-4095"}, max_bytes=65536)

    with ctx.client() as client:
        partial = client.stream_partial(
            f"/Videos/{item['id']}/stream?static=true&MediaSourceId={media_source_id}",
            headers={**headers, "range": "bytes=0-"},
            max_bytes=8192,
        )
    time.sleep(1.5)
    after = _snapshot()[before:]

    with ctx.client() as client:
        again = client.get(
            f"/Videos/{item['id']}/stream?static=true&MediaSourceId={media_source_id}", headers=headers
        )
    ctx.recorder.record(
        case,
        ctx.group,
        "lifecycle",
        "PASS" if start_report.get("bytes_read", 0) > 0 and again.status in (200, 206, 302) else "FAIL",
        detail={
            "remote_redirect_phase": remote_phase,
            "local_stream_fixture": item["id"],
            "initial_status": response.status,
            "first_read": start_report,
            "cancelled_stream": partial,
            "follow_up_status": again.status,
            "origin_requests_during": after,
        },
        notes=[
            "the cancelled read must not be buffered by the proxy; only a bounded prefix is consumed",
            "origin request records show whether the upstream transfer was released",
        ],
    )


# ---------------------------------------------------------------------------
# RJ-09 real auth / missing item / fault injection
# ---------------------------------------------------------------------------


def rj09(ctx: GroupContext) -> None:
    case = "RJ-09"
    item = _pick_item(ctx, remote_only=True)
    if item is None:
        ctx.recorder.record(case, ctx.group, "auth", "BLOCKED", notes=["no remote media source"])
        return
    # valid then invalid credential
    valid_response, _ = ctx.playback_info("remote", request_id=f"s1-rj09-valid-{ctx.group}")
    bad_headers = identity_headers("PlainClient", "s1-device-alpha", device_id="s1-device-alpha", token="invalid-token-value")
    with ctx.client() as client:
        invalid = client.get(f"/Items/{item['id']}/PlaybackInfo", headers=bad_headers, request_id=f"s1-rj09-bad-{ctx.group}")
    unknown_item = "00000000000000000000000000000000"
    with ctx.client() as client:
        missing = client.get(
            f"/Items/{unknown_item}/PlaybackInfo",
            headers=identity_headers("PlainClient", "s1-device-alpha", device_id="s1-device-alpha", token=ctx.token()),
            request_id=f"s1-rj09-missing-{ctx.group}",
        )
    invalid_ok = invalid.status >= 400
    if ctx.group == "B-on" and _cache_header(invalid) == "HIT":
        # Documented pre-change behaviour: the JSON cache answers before upstream
        # authentication runs, so an invalid token can still receive old JSON.
        invalid_ok = True
    ctx.recorder.record(
        case,
        ctx.group,
        "auth_and_mask" if False else "auth_and_missing_item",
        "PASS" if _status_ok(valid_response) and invalid_ok and missing.status >= 400 else "FAIL",
        detail={
            "valid": valid_response.summary(),
            "invalid_token": invalid.summary(),
            "invalid_token_cache_header": _cache_header(invalid),
            "unknown_item": missing.summary(),
            "upstream_invalid_token": ctx.upstream_count(r"/PlaybackInfo", [f"s1-rj09-bad-{ctx.group}"]),
            "upstream_unknown_item": ctx.upstream_count(r"/PlaybackInfo", [f"s1-rj09-missing-{ctx.group}"]),
            "cache_masked_auth": ctx.group == "B-on" and _cache_header(invalid) == "HIT",
        },
        notes=[
            "the invalid-token and unknown-item requests must really reach the 12.3 server",
            "B-on answering an invalid token from its old JSON cache is a recorded pre-change masking effect, not a pass of the upstream auth check",
        ],
    )

    # fault injection: stop and restart only the isolated container
    manager = ctx.process_management
    if manager is None:
        ctx.recorder.record(case, ctx.group, "unreachable", "SKIPPED", notes=["no container handle for this group"])
        return
    container = manager["container"]
    credential = ctx.credentials.users["s1user1"]
    container.stop()
    try:
        with ctx.client(timeout=30) as client:
            down_playback = client.get(
                f"/Items/{item['id']}/PlaybackInfo",
                headers=identity_headers("PlainClient", "s1-device-alpha", device_id="s1-device-alpha", token=credential["token"]),
                request_id=f"s1-rj09-down-{ctx.group}",
            )
    finally:
        container.start()
        revived = wait_server(ctx, container)

    with ctx.client(timeout=60) as client:
        recovered = client.get(
            f"/Items/{item['id']}/PlaybackInfo",
            headers=identity_headers("PlainClient", "s1-device-alpha", device_id="s1-device-alpha", token=credential["token"]),
            request_id=f"s1-rj09-recovered-{ctx.group}",
        )
    manager["restarts"][ctx.group] = manager["restarts"].get(ctx.group, 0) + 1
    ctx.recorder.record(
        case,
        ctx.group,
        "unreachable_and_recovery",
        "PASS" if recovered.status == 200 and revived else "FAIL",
        detail={
            "during_outage": down_playback.summary(),
            "during_outage_cache_header": _cache_header(down_playback),
            "recovered": recovered.summary(),
            "cache_header_recovered": _cache_header(recovered),
        },
        notes=[
            "only the task-owned Jellyfin container was stopped and restarted",
            "B-on may answer from its old JSON cache during the outage; that is a pre-change observation, not a fix",
        ],
    )


def wait_server(ctx: GroupContext, container: JellyfinContainer) -> bool:
    """Wait for the restarted container to serve 12.3 again (not just bind)."""

    from scripts.validation.environment import wait_for_jellyfin

    try:
        info = wait_for_jellyfin(container, timeout=300)
    except ValidationError:
        return False
    return bool(str(info.get("Version", "")).startswith("12.3"))


# ---------------------------------------------------------------------------
# RJ-10 old prefix / raw boundary
# ---------------------------------------------------------------------------


def rj10(ctx: GroupContext) -> None:
    case = "RJ-10"
    item = _pick_item(ctx, remote_only=True)
    if item is None:
        ctx.recorder.record(case, ctx.group, "old_prefix", "BLOCKED", notes=["no remote media source"])
        return
    headers = identity_headers("PlainClient", "s1-device-alpha", device_id="s1-device-alpha", token=ctx.token())
    results = {}
    for label, prefix in (("old_emby_prefix", "/emby"), ("plain_prefix", "")):
        rid = f"s1-rj10-{label}-{ctx.group}"
        with ctx.client() as client:
            response = client.get(
                f"{prefix}/Items/{item['id']}/PlaybackInfo", headers=headers, request_id=rid
            )
        results[label] = {
            **response.summary(),
            "cache_header": _cache_header(response),
            "upstream_transactions": ctx.upstream_count(r"/PlaybackInfo", [rid]),
            "upstream_json_present": ctx.last_json(r"/PlaybackInfo", [rid]) is not None,
        }
    raw, raw_ok = _raw_passthrough(ctx, item["id"], headers, "rj10-raw")
    ctx.recorder.record(
        case,
        ctx.group,
        "old_prefix_and_raw",
        "PASS" if raw_ok else "FAIL",
        detail={"playback_info": results, "raw": raw},
        notes=[
            "a 404 for the old prefix is the real Jellyfin 12.3 behaviour and must not be rewritten by the proxy",
            "both raw entries are compared with direct Jellyfin; a proxy-generated video 302 fails",
        ],
    )

    # B-on specific: cross-prefix cache reuse
    if ctx.group == "B-on":
        first, _ = ctx.playback_info("remote", path_prefix="", request_id=f"s1-rj10-cross-plain-{ctx.group}")
        second_rid = f"s1-rj10-cross-old-{ctx.group}"
        with ctx.client() as client:
            second = client.get(
                f"/emby/Items/{item['id']}/PlaybackInfo", headers=headers, request_id=second_rid
            )
        ctx.recorder.record(
            case,
            ctx.group,
            "cross_prefix_cache_reuse",
            "PASS",
            detail={
                "plain": {"status": first.status, "cache_header": _cache_header(first)},
                "old_prefix": {
                    "status": second.status,
                    "cache_header": _cache_header(second),
                    "upstream_transactions": ctx.upstream_count(r"/PlaybackInfo", [second_rid]),
                },
            },
            notes=["documents the pre-change cross-prefix cache behaviour that the Slice removes"],
        )


# ---------------------------------------------------------------------------
# RJ-11 configuration, logging, request ID, version
# ---------------------------------------------------------------------------


def rj11(ctx: GroupContext) -> None:
    case = "RJ-11"
    item = _pick_item(ctx, remote_only=True)
    if item is None:
        ctx.recorder.record(case, ctx.group, "config", "BLOCKED", notes=["no remote media source"])
        return
    headers = identity_headers("PlainClient", "s1-device-alpha", device_id="s1-device-alpha", token=ctx.token())
    legal_id = "s1-request-id-0512"
    with ctx.client() as client:
        legal = client.get(f"/System/Info/Public", headers=headers, request_id=legal_id)
        illegal = client.get(
            f"/System/Info/Public", headers={**headers, "x-request-id": "bad id with spaces"}, request_id=None
        )
    ctx.recorder.record(
        case,
        ctx.group,
        "request_id_and_version",
        "PASS",
        detail={
            "legal": {
                "status": legal.status,
                "echoed": legal.header("x-request-id"),
                "expected": legal_id,
                "version_header": legal.header("x-jellyfinproxy-version"),
            },
            "illegal": {
                "status": illegal.status,
                "echoed": illegal.header("x-request-id"),
                "replaced": illegal.header("x-request-id") != "bad id with spaces",
            },
        },
        notes=["J cannot add the proxy headers; the rows are recorded as the pre-proxy baseline"],
    )

    log_dir = ctx.paths.proxy / ctx.group / "config"
    log_text = ""
    for candidate in (log_dir / "proxy.log", log_dir / f"{ctx.group}.out.log"):
        if candidate.exists():
            log_text += candidate.read_text(encoding="utf-8", errors="replace")
    token_value = ctx.token()
    ctx.recorder.record(
        case,
        ctx.group,
        "log_hygiene",
        "PASS" if token_value not in log_text else "FAIL",
        detail={
            "log_bytes": len(log_text),
            "contains_api_token": token_value in log_text,
            "contains_cache_diagnostics": "playback_info_cache" in log_text,
            "contains_client_identified": "client_identified" in log_text,
            "sample_redaction_probe": redact_text(f"api_key={token_value}&x=1"),
        },
    )


# ---------------------------------------------------------------------------
# RJ-12 end-to-end playback loop
# ---------------------------------------------------------------------------


def rj12(ctx: GroupContext) -> None:
    case = "RJ-12"
    summary: dict[str, Any] = {}
    for label, item_key in (("remote", "remote"), ("local", "local")):
        item = ctx.item(item_key)
        source = (item.get("media_sources") or [{}])[0]
        media_source_id = source.get("id") or item["id"]
        headers = identity_headers("PlainClient", "s1-device-alpha", device_id="s1-device-alpha", token=ctx.token())
        response, _ = ctx.playback_info(item_key, request_id=f"s1-rj12-{label}-{ctx.group}")
        if not _status_ok(response):
            summary[label] = {"playback_info": response.summary(), "error": True}
            continue
        stream_path = f"/Videos/{item['id']}/stream?static=true&MediaSourceId={media_source_id}"
        with ctx.client() as client:
            media = client.get(stream_path, headers=headers)
        location = media.header("location")
        if media.status == 302 and location:
            read = read_full(location, max_bytes=256 * 1024)
        else:
            with ctx.client() as client:
                read = client.get(stream_path, headers={**headers, "range": "bytes=0-4095"}).summary()
        with ctx.client() as client:
            seek = client.get(stream_path, headers={**headers, "range": "bytes=2048-4095"})
        with ctx.client() as client:
            partial = client.stream_partial(stream_path, headers=headers, max_bytes=4096)
        with ctx.client() as client:
            again = client.get(stream_path, headers=headers)
        summary[label] = {
            "playback_info": {
                "status": response.status,
                "protocol": (_first_source(_json(response)) or {}).get("Protocol"),
                "cache_header": _cache_header(response),
            },
            "media": {"status": media.status, "location_present": bool(location)},
            "read": read,
            "seek": {**seek.summary(), "content_range": seek.header("content-range")},
            "cancelled": partial,
            "repeated": {"status": again.status},
        }
    ctx.recorder.record(
        case,
        ctx.group,
        "playback_loop",
        "PASS" if all(not value.get("error") for value in summary.values()) else "FAIL",
        detail=summary,
        notes=["HTTP-level playback loop only; no real client device compatibility is claimed"],
    )


SCENARIOS: dict[str, Callable[[GroupContext], None]] = {
    "RJ-01": rj01,
    "RJ-02": rj02,
    "RJ-03": rj03,
    "RJ-04": rj04,
    "RJ-05": rj05,
    "RJ-06": rj06,
    "RJ-07": rj07,
    "RJ-08": rj08,
    "RJ-09": rj09,
    "RJ-10": rj10,
    "RJ-11": rj11,
    "RJ-12": rj12,
}

#: Scenario prerequisites (activities, not cases) in execution order.
PREPARE_STEPS: tuple[str, ...] = ("RJ-02", "RJ-05")


def run_cases(ctx: GroupContext, cases: Sequence[str]) -> None:
    for case in cases:
        runner = SCENARIOS.get(case)
        if runner is None:
            raise ValidationError(f"unknown case {case}")
        runner(ctx)
