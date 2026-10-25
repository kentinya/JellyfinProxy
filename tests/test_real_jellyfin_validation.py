"""Deterministic tests for the real Jellyfin 12.3 validation tooling.

These tests cover the tool itself (counting, comparisons, redaction, CLI failure
modes, ownership-safe stop) against local fake inputs. They do not and cannot
replace the real-server baseline in ``artifacts/validation-evidence/S1``.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.validation import evidence, json_diff, media_server
from scripts.validation.common import (
    PRODUCT_BASE,
    REQUIRED_SERVER_VERSION,
    ValidationError,
    canonical_json,
    redact,
    redact_text,
    sha256_bytes,
    url_digest,
)
from scripts.validation.environment import (
    RUN_MARKER,
    RUN_MARKER_LABEL,
    RunPaths,
    assert_owned_run_dir,
    build_lock,
    prepare_run_dir,
    resolve_ports,
    stop_run,
    tool_identity,
    verify_lock,
)
from scripts.validation.proxy_runner import (
    PRODUCT_ENV_VARS,
    clean_environment,
    proxy_config,
    toml_dumps,
)
from scripts.validation import supplement

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# redaction
# ---------------------------------------------------------------------------


def test_redact_text_masks_query_credentials_and_mediabrowser_token() -> None:
    raw = (
        "GET /Items?api_key=SUPERSECRETVALUE123456&x-emby-token=another-value "
        'Authorization: MediaBrowser Client="a", Device="b", Token=abcdef1234567890'
    )
    cleaned = redact_text(raw)
    assert "SUPERSECRETVALUE123456" not in cleaned
    assert "another-value" not in cleaned
    assert "abcdef1234567890" not in cleaned
    assert "api_key=[REDACTED]" in cleaned
    assert "Token=[REDACTED]" in cleaned


def test_redact_structure_masks_credential_keys_and_signed_urls() -> None:
    payload = {
        "AccessToken": "token-value-should-vanish",
        "nested": [{"Pw": "hunter2", "Path": "https://cdn.example/x.mkv?token=SEKRET"}],
        "MediaSources": [{"Protocol": "File", "SupportsTranscoding": False}],
    }
    cleaned = redact(payload)
    assert cleaned["AccessToken"] == "[REDACTED]"
    assert cleaned["nested"][0]["Pw"] == "[REDACTED]"
    assert "SEKRET" not in json.dumps(cleaned)
    # non-credential business values keep their meaning for comparisons
    assert cleaned["MediaSources"][0]["Protocol"] == "File"
    assert cleaned["MediaSources"][0]["SupportsTranscoding"] is False


def test_url_digest_distinguishes_different_urls_and_not_redaction() -> None:
    first = "https://cdn.example/a.mkv?token=one"
    second = "https://cdn.example/a.mkv?token=two"
    assert url_digest(first) != url_digest(second)
    report = json_diff.url_equality_report(first, second)
    assert report["equal"] is False
    # the report never contains the raw URL
    assert "cdn.example" not in json.dumps(report)


# ---------------------------------------------------------------------------
# field comparison / dynamic whitelist
# ---------------------------------------------------------------------------


def test_compare_json_ignores_documented_dynamic_fields_only() -> None:
    baseline = {
        "PlaySessionId": "aaa",
        "MediaSources": [{"Path": "https://cdn/a.mkv", "ETag": "1", "Protocol": "Http"}],
    }
    candidate = {
        "PlaySessionId": "bbb",
        "MediaSources": [{"Path": "https://cdn/a.mkv", "ETag": "2", "Protocol": "Http"}],
    }
    assert json_diff.compare_json(baseline, candidate) == []


def test_compare_json_reports_unexpected_field_change_with_location() -> None:
    baseline = {"MediaSources": [{"Path": "https://cdn/a.mkv", "SupportsTranscoding": True}]}
    candidate = {"MediaSources": [{"Path": "https://cdn/a.mkv", "SupportsTranscoding": False}]}
    differences = json_diff.compare_json(baseline, candidate)
    summary = json_diff.summarize_differences(differences)
    assert summary["unexpected"] == ["MediaSources[].SupportsTranscoding"]
    assert summary["count"] == 1


def test_compare_json_detects_presence_and_length_changes() -> None:
    baseline = {"MediaSources": [{"Id": "x"}], "Keep": 1}
    candidate = {"MediaSources": [{"Id": "x"}, {"Id": "y"}]}
    summary = json_diff.summarize_differences(json_diff.compare_json(baseline, candidate))
    assert "MediaSources[]" in summary["unexpected"]
    assert "Keep" in summary["unexpected"]


def test_compare_json_allows_explicit_per_scenario_whitelist() -> None:
    baseline = {"MediaSources": [{"TranscodingUrl": "a"}]}
    candidate = {"MediaSources": [{"TranscodingUrl": "b"}]}
    assert json_diff.compare_json(baseline, candidate) != []
    assert json_diff.compare_json(
        baseline, candidate, allow_suffixes=["MediaSources[].TranscodingUrl"]
    ) == []


def test_normalize_location_terminates_on_index_patterns() -> None:
    # regression: the previous implementation looped forever because "[]" contains "["
    assert json_diff._normalize_location("MediaSources[0].Path") == "MediaSources[].Path"
    assert json_diff._normalize_location("A[1][2].b") == "A[][].b"
    assert json_diff._normalize_location("PlaySessionId") == "PlaySessionId"


def test_dynamic_locations_are_documented() -> None:
    for location, reason in json_diff.DYNAMIC_LOCATIONS.items():
        assert reason.strip(), f"{location} has no documented reason"


# ---------------------------------------------------------------------------
# counts and evidence helpers
# ---------------------------------------------------------------------------


def test_case_status_counts_only_passes() -> None:
    results = {
        "a": {"case": "RJ-01", "group": "J", "status": "PASS"},
        "b": {"case": "RJ-01", "group": "J", "status": "FAIL"},
        "c": {"case": "RJ-02", "group": "B-on", "status": "PASS"},
    }
    assert evidence.case_status(results) == {"J": {"RJ-01": 1}, "B-on": {"RJ-02": 1}}


def test_canonical_json_is_stable_and_sorted() -> None:
    left = canonical_json({"b": 1, "a": [2, 1]})
    right = canonical_json({"a": [2, 1], "b": 1})
    assert left == right
    assert sha256_bytes(left) == sha256_bytes(right)


# ---------------------------------------------------------------------------
# run directory ownership and stop
# ---------------------------------------------------------------------------


def test_prepare_run_dir_creates_owner_marker_and_private_dirs(tmp_path: Path) -> None:
    paths = prepare_run_dir(tmp_path / "run")
    assert paths.marker.exists()
    marker = json.loads(paths.marker.read_text())
    assert marker["label"] == RUN_MARKER_LABEL
    assert stat.S_IMODE(paths.private.stat().st_mode) == 0o700
    assert stat.S_IMODE(paths.evidence.stat().st_mode) == 0o700
    assert_owned_run_dir(paths)


def test_assert_owned_run_dir_refuses_foreign_directory(tmp_path: Path) -> None:
    foreign = RunPaths(root=tmp_path / "foreign")
    foreign.root.mkdir()
    with pytest.raises(ValidationError):
        assert_owned_run_dir(foreign)


def test_stop_run_refuses_directory_without_marker(tmp_path: Path) -> None:
    foreign = RunPaths(root=tmp_path / "foreign")
    foreign.root.mkdir()
    (foreign.root / RUN_MARKER).write_text(json.dumps({"label": "someone-else"}))
    with pytest.raises(ValidationError):
        stop_run(foreign)


def test_stop_run_is_idempotent_and_records_actions(tmp_path: Path) -> None:
    paths = prepare_run_dir(tmp_path / "run")
    first = stop_run(paths)
    second = stop_run(paths)
    assert first["actions"]
    assert second["actions"]
    # a run with no container/proxy leaves foreign resources alone
    assert all("mismatch" not in action for action in second["actions"])


def test_stop_run_ignores_unowned_records(tmp_path: Path) -> None:
    paths = prepare_run_dir(tmp_path / "run")
    paths.manifest.write_text(json.dumps({"run_id": "x", "proxy_processes": [], "tool_processes": []}))
    result = stop_run(paths)
    assert "no owned container present" in result["actions"]


# ---------------------------------------------------------------------------
# server lock / ports
# ---------------------------------------------------------------------------


def _image(reference: str = "jellyfin/jellyfin:12.3") -> dict:
    return {
        "reference": reference,
        "id": "sha256:deadbeef",
        "repo_digests": [f"{reference.split(':')[0]}@sha256:" + "a" * 64],
        "architecture": "amd64",
        "os": "linux",
        "labels": {"org.opencontainers.image.version": "12.3"},
    }


def _lock() -> dict:
    return build_lock(
        _image(),
        {"Version": "12.3.0", "Id": "server-id", "ServerName": "s1"},
        {"jellyfin": 18096},
    )


def test_build_lock_records_digest_version_and_product_base() -> None:
    lock = _lock()
    assert lock["image_digest"] == "sha256:" + "a" * 64
    assert lock["server_version"] == "12.3.0"
    assert lock["required_server_version"] == REQUIRED_SERVER_VERSION
    assert lock["product_base"] == PRODUCT_BASE


def test_build_lock_fails_without_digest() -> None:
    image = _image()
    image["repo_digests"] = []
    with pytest.raises(ValidationError):
        build_lock(image, {"Version": "12.3.0"}, {"jellyfin": 18096})


def test_verify_lock_rejects_version_drift_and_base_drift() -> None:
    lock = _lock()
    verify_lock(lock, reference="jellyfin/jellyfin:12.3")

    drifted = dict(lock, server_version="12.4.0")
    with pytest.raises(ValidationError):
        verify_lock(drifted, reference="jellyfin/jellyfin:12.3")

    mixed = dict(lock, product_base="0" * 40)
    with pytest.raises(ValidationError):
        verify_lock(mixed, reference="jellyfin/jellyfin:12.3")

    other_image = dict(lock, image_reference="jellyfin/jellyfin:latest")
    with pytest.raises(ValidationError):
        verify_lock(other_image, reference="jellyfin/jellyfin:12.3")


def test_resolve_ports_refuses_occupied_port() -> None:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen(1)
        port = occupied.getsockname()[1]
        with pytest.raises(ValidationError):
            resolve_ports({"jellyfin": port, "observatory": port + 1})


def test_resolve_ports_allows_ports_owned_by_this_run() -> None:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen(1)
        port = occupied.getsockname()[1]
        chosen = resolve_ports({"jellyfin": port}, owned=[port])
        assert chosen["jellyfin"] == port


# ---------------------------------------------------------------------------
# proxy control-group configuration
# ---------------------------------------------------------------------------


def test_proxy_config_only_differs_by_cache_switch() -> None:
    common = dict(
        upstream_url="http://127.0.0.1:18097",
        port=18098,
        profile="matrix",
        log_dir=Path("/tmp/x"),
    )
    on = proxy_config(cache_enabled=True, **common)
    off = proxy_config(cache_enabled=False, **common)
    assert on["playback_info_cache_enabled"] is True
    assert off["playback_info_cache_enabled"] is False
    assert {k: v for k, v in on.items() if k != "playback_info_cache_enabled"} == {
        k: v for k, v in off.items() if k != "playback_info_cache_enabled"
    }
    # the old-default values are pinned so the control group is the real baseline
    assert on["playback_info_cache_ttl_seconds"] == 21600
    assert on["playback_info_cache_max_entries"] == 4096


def test_proxy_config_rejects_unknown_profile() -> None:
    with pytest.raises(ValidationError):
        proxy_config(
            upstream_url="http://127.0.0.1:1",
            port=1,
            profile="nope",
            log_dir=Path("/tmp/x"),
            cache_enabled=True,
        )


def test_toml_dumps_roundtrips_into_valid_toml() -> None:
    import tomllib

    payload = proxy_config(
        upstream_url="http://127.0.0.1:18097",
        port=18098,
        profile="matrix",
        log_dir=Path("/tmp/x"),
        cache_enabled=True,
    )
    parsed = tomllib.loads(toml_dumps(payload))
    assert parsed["listen_port"] == 18098
    assert parsed["bypass_clients"] == ["GlobalClient"]
    assert parsed["playback_info_cache_enabled"] is True


def test_clean_environment_drops_product_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLAYBACK_INFO_CACHE_ENABLED", "false")
    monkeypatch.setenv("JELLYFIN_URL", "http://production.example:8096")
    monkeypatch.setenv("PYTHONPATH", "/tmp/injected")
    env = clean_environment({"S1_OBS_TARGET": "http://127.0.0.1:18096"})
    for name in PRODUCT_ENV_VARS:
        assert name not in env
    assert "PYTHONPATH" not in env
    assert env["S1_OBS_TARGET"] == "http://127.0.0.1:18096"


# ---------------------------------------------------------------------------
# media origin
# ---------------------------------------------------------------------------


def test_media_origin_serves_ranges_and_records_requests(tmp_path: Path) -> None:
    import httpx

    payload = bytes(range(256)) * 64
    (tmp_path / "clip.mp4").write_bytes(payload)
    server = media_server.MediaServer(tmp_path, 0)
    with server:
        port = server._servers[0].server_address[1]
        base = f"http://127.0.0.1:{port}"
        # rebind with the actual ephemeral port for URL building
        server.port = port
        full = httpx.get(f"{base}/clip.mp4", timeout=10)
        ranged = httpx.get(f"{base}/clip.mp4", headers={"Range": "bytes=10-19"}, timeout=10)
        missing = httpx.get(f"{base}/nope.mp4", timeout=10)
    assert full.status_code == 200 and len(full.content) == len(payload)
    assert ranged.status_code == 206
    assert ranged.content == payload[10:20]
    assert ranged.headers["content-range"] == f"bytes 10-19/{len(payload)}"
    assert missing.status_code == 404
    snapshot = server.state.snapshot()
    assert [row["status"] for row in snapshot] == [200, 206, 404]
    assert snapshot[1]["bytes_sent"] == 10
    assert snapshot[1]["range"] == "bytes=10-19"


def test_media_origin_rejects_parent_traversal(tmp_path: Path) -> None:
    import httpx

    (tmp_path / "ok.mp4").write_bytes(b"x")
    secret = tmp_path.parent / "secret.txt"
    secret.write_bytes(b"secret")
    server = media_server.MediaServer(tmp_path, 0)
    try:
        server.start()
        port = server._servers[0].server_address[1]
        response = httpx.get(f"http://127.0.0.1:{port}/../secret.txt", timeout=10)
    finally:
        server.stop()
        secret.unlink(missing_ok=True)
    assert response.status_code == 404


def test_media_origin_inventory_reports_digests(tmp_path: Path) -> None:
    (tmp_path / "a.mp4").write_bytes(b"abc")
    server = media_server.MediaServer(tmp_path, 9999)
    inventory = server.inventory()
    assert inventory["a.mp4"]["size"] == 3
    assert inventory["a.mp4"]["sha256"] == sha256_bytes(b"abc")


# ---------------------------------------------------------------------------
# CLI failure modes (no network, no docker mutation)
# ---------------------------------------------------------------------------


def _run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "validate_jellyfin_12_3.py"), *arguments],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=300,
    )


def test_cli_rejects_unsupported_server_version(tmp_path: Path) -> None:
    completed = _run_cli("doctor", "--run-dir", str(tmp_path), "--server-version", "12.4")
    assert completed.returncode != 0
    assert "12.3" in (completed.stdout + completed.stderr)


def test_cli_baseline_requires_prepared_manifest(tmp_path: Path) -> None:
    completed = _run_cli("baseline", "--run-dir", str(tmp_path))
    assert completed.returncode != 0
    assert "marker" in (completed.stdout + completed.stderr)


def test_cli_verify_evidence_reports_missing_inputs(tmp_path: Path) -> None:
    completed = _run_cli("verify-evidence", "--run-dir", str(tmp_path))
    assert completed.returncode != 0
    assert "run_dir_ownership" in (completed.stdout + completed.stderr)


def test_cli_unknown_case_is_rejected(tmp_path: Path) -> None:
    paths = prepare_run_dir(tmp_path / "run")
    completed = _run_cli("baseline", "--run-dir", str(paths.root), "--cases", "RJ-99")
    combined = completed.stdout + completed.stderr
    assert completed.returncode != 0
    assert "RJ-99" in combined


# ---------------------------------------------------------------------------
# evidence verification
# ---------------------------------------------------------------------------


def _seed_evidence(paths: RunPaths, *, results, leaked_token: str | None = None) -> None:
    import hashlib

    from scripts.validation.common import write_json

    base_sha = PRODUCT_BASE
    (paths.base_src).mkdir(parents=True, exist_ok=True)
    (paths.base_src / "main.py").write_text("print('x')\n")
    write_json(
        paths.base_src / "SOURCE_IDENTITY.json",
        {
            "base_ref": base_sha,
            "base_sha": base_sha,
            "files": {"main.py": hashlib.sha256(b"print('x')\n").hexdigest()},
        },
    )
    write_json(
        paths.manifest,
        {
            "run_id": "test-run",
            "tool": {"tool_head": "f" * 40},
            "product_base": {"base_ref": base_sha, "base_sha": base_sha},
            "runtime_version": {"server_version": "12.3.0"},
            "groups": ["J"],
        },
    )
    write_json(
        paths.lock,
        {
            "server_version": "12.3.0",
            "image_digest": "sha256:" + "b" * 64,
            "product_base": base_sha,
            "required_server_version": "12.3",
            "image_reference": "jellyfin/jellyfin:12.3",
        },
    )
    write_json(paths.evidence / "results.json", results)
    for group in ("J",):
        (paths.evidence / f"transactions-{group}.jsonl").write_text("")
    write_json(paths.evidence / "stop.json", {"actions": ["stopped x"], "idempotent_repeat": True})
    write_json(
        paths.credentials,
        {"admin_token": "admin-token-value", "users": {"u": {"token": "user-token-value", "password": "pw-value"}}},
    )
    if leaked_token:
        (paths.evidence / "leak.txt").write_text(f"Authorization: MediaBrowser Token={leaked_token}\n")


def test_verify_evidence_passes_for_complete_redacted_bundle(tmp_path: Path) -> None:
    paths = prepare_run_dir(tmp_path / "run")
    results = {}
    for index in range(1, 13):
        case = f"RJ-{index:02d}"
        results[f"{case}:J:x"] = {"case": case, "group": "J", "subcase": "x", "status": "PASS", "detail": {}}
    _seed_evidence(paths, results=results)
    report = evidence.verify(paths, expected_cases=[f"RJ-{i:02d}" for i in range(1, 13)])
    failing = [check for check in report.checks if check["status"] == "FAIL"]
    assert failing == [], failing


def test_verify_evidence_detects_missing_case(tmp_path: Path) -> None:
    paths = prepare_run_dir(tmp_path / "run")
    _seed_evidence(paths, results={})
    report = evidence.verify(paths, expected_cases=["RJ-01"])
    checks = {check["check"]: check for check in report.checks}
    assert checks["required_case_coverage"]["status"] == "FAIL"


def test_verify_evidence_detects_failing_subcase(tmp_path: Path) -> None:
    paths = prepare_run_dir(tmp_path / "run")
    results = {"RJ-01:J:x": {"case": "RJ-01", "group": "J", "subcase": "x", "status": "FAIL", "detail": {}}}
    _seed_evidence(paths, results=results)
    report = evidence.verify(paths, expected_cases=["RJ-01"])
    checks = {check["check"]: check for check in report.checks}
    assert checks["required_case_results"]["status"] == "FAIL"


def test_verify_evidence_detects_leaked_credential(tmp_path: Path) -> None:
    paths = prepare_run_dir(tmp_path / "run")
    results = {"RJ-01:J:x": {"case": "RJ-01", "group": "J", "subcase": "x", "status": "PASS", "detail": {}}}
    _seed_evidence(paths, results=results, leaked_token="user-token-value")
    report = evidence.verify(paths, expected_cases=["RJ-01"])
    checks = {check["check"]: check for check in report.checks}
    assert checks["evidence_redaction"]["status"] == "FAIL"


def test_verify_evidence_detects_tampered_product_source(tmp_path: Path) -> None:
    paths = prepare_run_dir(tmp_path / "run")
    results = {"RJ-01:J:x": {"case": "RJ-01", "group": "J", "subcase": "x", "status": "PASS", "detail": {}}}
    _seed_evidence(paths, results=results)
    (paths.base_src / "main.py").write_text("print('tampered')\n")
    report = evidence.verify(paths, expected_cases=["RJ-01"])
    checks = {check["check"]: check for check in report.checks}
    assert checks["product_source_identity"]["status"] == "FAIL"


def test_verify_evidence_detects_version_drift(tmp_path: Path) -> None:
    paths = prepare_run_dir(tmp_path / "run")
    results = {"RJ-01:J:x": {"case": "RJ-01", "group": "J", "subcase": "x", "status": "PASS", "detail": {}}}
    _seed_evidence(paths, results=results)
    manifest = json.loads(paths.manifest.read_text())
    manifest["runtime_version"] = {"server_version": "12.4.0"}
    paths.manifest.write_text(json.dumps(manifest))
    report = evidence.verify(paths, expected_cases=["RJ-01"])
    checks = {check["check"]: check for check in report.checks}
    assert checks["runtime_server_version"]["status"] == "FAIL"


def test_verify_evidence_flags_unexpected_j_differences(tmp_path: Path) -> None:
    paths = prepare_run_dir(tmp_path / "run")
    results = {
        "RJ-03:J:x": {
            "case": "RJ-03",
            "group": "J",
            "subcase": "x",
            "status": "PASS",
            "detail": {"differences": {"unexpected": ["MediaSources[].Protocol"]}},
        }
    }
    _seed_evidence(paths, results=results)
    report = evidence.verify(paths, expected_cases=["RJ-03"])
    checks = {check["check"]: check for check in report.checks}
    assert checks["dynamic_whitelist_only"]["status"] == "FAIL"


def test_tool_identity_lists_committed_tool_files() -> None:
    identity = tool_identity()
    assert identity["tool_head"]
    assert "scripts/validate_jellyfin_12_3.py" in identity["tool_files_sha256"]


# ---------------------------------------------------------------------------
# S1.1 functional supplement helpers
# ---------------------------------------------------------------------------


def test_supplement_profiles_overlap_is_a_real_product_configuration() -> None:
    """The supplement must use an existing product matrix, not an invented one."""

    config = proxy_config(
        upstream_url="http://127.0.0.1:18096",
        port=18098,
        profile=supplement.PROFILE,
        log_dir=Path("/tmp/x"),
        cache_enabled=False,
    )
    parsed = __import__("tomllib").loads(toml_dumps(config))
    assert supplement.PROFILE == "matrix_overlap"
    assert "OverlapClient" in parsed["playback_bypass_clients"]
    assert "OverlapClient" in parsed["video_bypass_clients"]
    assert "GlobalClient" in parsed["bypass_clients"]
    assert parsed["playback_info_cache_enabled"] is False
    assert supplement.GROUP_CACHE == {"B-on": True, "B-off": False}


def test_supplement_overlap_identity_is_configured_globally_and_per_route() -> None:
    """The overlap row must be the real global/branch intersection."""

    config = proxy_config(
        upstream_url="http://127.0.0.1:18096",
        port=18098,
        profile=supplement.PROFILE,
        log_dir=Path("/tmp/x"),
        cache_enabled=True,
    )
    for key in ("bypass_clients", "playback_bypass_clients", "video_bypass_clients"):
        assert "OverlapClient" in config[key], key
    # The plain (single-route) matrix must not silently gain the overlap client.
    plain = proxy_config(
        upstream_url="http://127.0.0.1:18096",
        port=18098,
        profile="matrix",
        log_dir=Path("/tmp/x"),
        cache_enabled=False,
    )
    assert "OverlapClient" not in plain["bypass_clients"]
    assert "OverlapClient" not in plain["video_bypass_clients"]


def test_supplement_id_priority_rows_use_two_seeded_query_names() -> None:
    """The query-name conflict rows must mix both spellings of one parameter."""

    import inspect

    source = inspect.getsource(supplement.check_id_resolution)
    # Both spellings appear inside a single URL, i.e. a real conflict, not two
    # separate rows that each use only one spelling.
    assert source.count("MediaSourceId=") >= 2
    assert "mediaSourceId=" in source
    assert "seeds" in source


def test_supplement_second_mapping_is_not_reseeded_after_the_cycle_starts() -> None:
    """V1 must not re-request the second id's PlaybackInfo during the cycle."""

    import inspect

    source = inspect.getsource(supplement.check_second_mapping_preserved)
    step_body = source.split("def step(", 1)[1].split("step(\"valid_remote_a\"", 1)[0]
    # The step may request the target id's PlaybackInfo, but never the second id's.
    assert "second_id" not in step_body
    assert "second_video = session.video(second_stream)" in step_body


def test_supplement_origin_summary_detects_early_release() -> None:
    released = supplement._origin_summary(
        [
            {"bytes_sent": 32768, "aborted_by_client": True, "finished": False},
        ],
        full_size=85112,
    )
    assert released["entries"] == 1
    assert released["any_aborted_by_reader"] is True
    assert released["released_before_full_size"] is True
    assert released["max_bytes_sent"] == 32768

    completed = supplement._origin_summary(
        [
            {"bytes_sent": 85112, "aborted_by_client": False, "finished": True},
        ],
        full_size=85112,
    )
    assert completed["any_aborted_by_reader"] is False
    assert completed["released_before_full_size"] is False

    empty = supplement._origin_summary([], full_size=85112)
    assert empty["entries"] == 0
    assert empty["released_before_full_size"] is False


def test_supplement_throttle_target_keeps_the_playable_origin_file() -> None:
    """The slowed fixture must still point at a real origin asset, only slower."""

    assert supplement.THROTTLE_TARGET.startswith("remote-a.mp4?throttle=")
    rate = int(supplement.THROTTLE_TARGET.split("throttle=")[1])
    assert rate > 0


def test_supplement_digest_helpers_are_stable_and_short() -> None:
    assert supplement._digest("") is None
    first = supplement._digest("http://172.17.0.1:18100/remote-a.mp4")
    assert first == supplement._digest("http://172.17.0.1:18100/remote-a.mp4")
    assert first != supplement._digest("http://172.17.0.1:18100/remote-b.mp4")
    assert len(first) == 16


def test_supplement_cli_rejects_unknown_group(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "validation" / "supplement.py"),
            "--run-dir",
            str(tmp_path),
            "--groups",
            "B-on,Observatory",
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=300,
    )
    combined = completed.stdout + completed.stderr
    assert completed.returncode != 0
    assert "Observatory" in combined
