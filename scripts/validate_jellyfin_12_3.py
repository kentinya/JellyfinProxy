#!/usr/bin/env python3
"""CLI for the real Jellyfin 12.3 baseline (Slice S1.1).

Commands:

  doctor          dependency / port / version-capability preflight (read-only)
  prepare         create the isolated environment and lock the official 12.3 build
  baseline        run the RJ-01..RJ-12 baseline for J, B-on and B-off
  stop            stop only the resources owned by this run directory
  verify-evidence check identity, completeness, whitelist and redaction

Everything is test tooling. It never changes product behaviour and never writes
to a non-owned directory or container.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if os.environ.get("S1_FAULTHANDLER_TIMEOUT"):
    import faulthandler

    faulthandler.dump_traceback_later(float(os.environ["S1_FAULTHANDLER_TIMEOUT"]), repeat=True)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.validation import common  # noqa: E402
from scripts.validation.common import (  # noqa: E402
    DEFAULT_PORTS,
    PRODUCT_BASE,
    REQUIRED_SERVER_VERSION,
    ValidationError,
    ensure_directory,
    environment_fingerprint,
    port_is_free,
    read_json,
    utc_now,
    write_json,
    write_text,
)
from scripts.validation import environment  # noqa: E402
from scripts.validation.environment import (  # noqa: E402
    JellyfinContainer,
    RunPaths,
    append_proxy_process,
    assert_owned_run_dir,
    build_lock,
    container_host_ports,
    docker_available,
    docker_compose_version,
    extract_base_source,
    git_rev,
    image_inspect,
    image_present,
    image_reference,
    load_manifest,
    port_owner_hint,
    prepare_run_dir,
    pull_image,
    resolve_ports,
    stop_run,
    tool_identity,
    update_manifest,
    verify_lock,
    wait_for_jellyfin,
)
from scripts.validation import evidence  # noqa: E402
from scripts.validation import fixtures  # noqa: E402
from scripts.validation.media_server import MediaServer  # noqa: E402
from scripts.validation.proxy_runner import (  # noqa: E402
    ProcessSupervisor,
    launch_observatory,
    launch_proxy,
    set_observatory_group,
)
from scripts.validation.scenarios import (  # noqa: E402
    GROUPS,
    SCENARIOS,
    GroupContext,
    ResultRecorder,
    _set_strm_and_refresh,
    run_cases,
)

REQUIRED_CASES = tuple(f"RJ-{index:02d}" for index in range(1, 13))
NETWORK_TIMEOUT = 240


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Real Jellyfin 12.3 validation tool (Slice S1.1)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="read-only dependency and port preflight")
    doctor.add_argument("--run-dir", type=Path, required=True)
    doctor.add_argument("--server-version", default=REQUIRED_SERVER_VERSION)

    prepare = subparsers.add_parser("prepare", help="create the isolated environment and lock the build")
    prepare.add_argument("--run-dir", type=Path, required=True)
    prepare.add_argument("--server-version", default=REQUIRED_SERVER_VERSION)
    prepare.add_argument("--base-ref", default=PRODUCT_BASE)
    prepare.add_argument("--server-lock", type=Path, default=None)
    prepare.add_argument("--reuse-container", action="store_true", default=True)
    prepare.add_argument("--skip-pull", action="store_true")

    baseline = subparsers.add_parser("baseline", help="run the J / B-on / B-off baseline")
    baseline.add_argument("--run-dir", type=Path, required=True)
    baseline.add_argument("--cases", default="", help="comma separated RJ ids; default: all applicable")
    baseline.add_argument("--groups", default=",".join(GROUPS))

    stop = subparsers.add_parser("stop", help="stop resources owned by this run directory")
    stop.add_argument("--run-dir", type=Path, required=True)
    stop.add_argument("--remove-files", action="store_true")

    verify = subparsers.add_parser("verify-evidence", help="verify the evidence bundle")
    verify.add_argument("--run-dir", type=Path, required=True)
    verify.add_argument("--cases", default="")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    started = time.monotonic()
    try:
        if arguments.command == "doctor":
            exit_code = command_doctor(arguments)
        elif arguments.command == "prepare":
            exit_code = command_prepare(arguments)
        elif arguments.command == "baseline":
            exit_code = command_baseline(arguments)
        elif arguments.command == "stop":
            exit_code = command_stop(arguments)
        elif arguments.command == "verify-evidence":
            exit_code = command_verify(arguments)
        else:  # pragma: no cover - argparse guards this
            raise ValidationError(f"unknown command {arguments.command}")
    except ValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        print(f"command={arguments.command} duration_seconds={time.monotonic() - started:.1f}")
    return exit_code


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


def command_doctor(arguments: argparse.Namespace) -> int:
    run_dir = arguments.run_dir.resolve()
    print(f"run_dir={run_dir}")
    print(f"cwd={Path.cwd()}")
    print("environment=" + json.dumps(environment_fingerprint(), ensure_ascii=False))
    if arguments.server_version != REQUIRED_SERVER_VERSION:
        raise ValidationError(
            f"this tool implements the {REQUIRED_SERVER_VERSION} contract; --server-version {arguments.server_version} is not supported"
        )

    docker_ok, docker_version = docker_available()
    print(f"docker={docker_version} available={docker_ok}")
    compose_version = docker_compose_version()
    print(f"compose={compose_version}")
    disk = shutil.disk_usage(run_dir.parent if run_dir.parent.exists() else Path("/"))
    print(f"disk_available_gib={disk.free / (1 << 30):.1f}")

    problems: list[str] = []
    if not docker_ok:
        problems.append("docker client/server unavailable")
    if docker_ok:
        reference = image_reference()
        print(f"image_reference={reference} present={image_present(reference)}")
    for name, port in DEFAULT_PORTS.items():
        free = port_is_free(port)
        owner = "" if free else port_owner_hint(port)
        print(f"port {name}={port} free={free}" + (f" owner={owner}" if owner else ""))
        if not free:
            problems.append(f"port {port} ({name}) already in use")

    base_sha = git_rev(arguments_base_ref(arguments, PRODUCT_BASE))
    print(f"product_base={PRODUCT_BASE} resolved={base_sha}")
    if base_sha != PRODUCT_BASE:
        problems.append(f"product base resolved to {base_sha}, expected {PRODUCT_BASE}")

    venv_python = REPO_ROOT / ".venv" / "bin" / "python"
    print(f"venv_python={venv_python} exists={venv_python.exists()}")
    if not venv_python.exists():
        problems.append("missing .venv interpreter")
    for module in ("fastapi", "httpx", "uvicorn", "pytest"):
        available = __import__("importlib").util.find_spec(module) is not None
        print(f"module {module} available={available}")
        if not available:
            problems.append(f"missing Python dependency {module}")
    ffprobe = shutil.which("ffprobe")
    print(f"host_ffprobe={ffprobe} (optional; the pinned image provides ffmpeg)")
    print(f"ready={not problems}")
    if problems:
        for problem in problems:
            print(f"  blocked: {problem}", file=sys.stderr)
        return 3
    return 0


def arguments_base_ref(arguments: argparse.Namespace, default: str) -> str:
    return getattr(arguments, "base_ref", default) or default


# ---------------------------------------------------------------------------
# prepare
# ---------------------------------------------------------------------------


def command_prepare(arguments: argparse.Namespace) -> int:
    if arguments.server_version != REQUIRED_SERVER_VERSION:
        raise ValidationError(
            f"only Jellyfin {REQUIRED_SERVER_VERSION} is supported by this contract; got {arguments.server_version}"
        )
    paths = prepare_run_dir(arguments.run_dir)
    manifest = read_json(paths.manifest) if paths.manifest.exists() else {}
    run_id = manifest.get("run_id") or f"{paths.root.name}-{utc_now().replace(':', '')}"

    reference = image_reference()
    lock_payload: dict[str, Any] | None = None
    if arguments.server_lock is not None:
        source_lock = arguments.server_lock.resolve()
        if not source_lock.exists():
            raise ValidationError(f"--server-lock {source_lock} does not exist")
        lock_payload = read_json(source_lock)
        verify_lock(lock_payload, reference=reference)
        print(f"using locked build digest={lock_payload['image_digest']} version={lock_payload['server_version']}")
        if not image_present(lock_payload["image_reference"]):
            pull_image(lock_payload["image_reference"])
        reference = lock_payload["image_reference"]
    else:
        if paths.lock.exists():
            lock_payload = read_json(paths.lock)
            verify_lock(lock_payload, reference=reference)
            print(f"reusing existing lock digest={lock_payload['image_digest']}")
        elif not arguments.skip_pull:
            pull_image(reference)

    if not image_present(reference):
        raise ValidationError(f"image {reference} is not present locally and pulling was skipped")

    container_name = _container_name(run_id)
    owned_ports: list[int] = []
    if run_command_is_owned(container_name):
        owned_ports = list(container_host_ports(container_name))

    ports = resolve_ports(owned=owned_ports)
    print("ports=" + json.dumps(ports))

    # extract the fixed product base for the control groups
    base_payload = extract_base_source(arguments.base_ref, paths.base_src)
    if base_payload["base_sha"] != arguments.base_ref:
        raise ValidationError(
            f"--base-ref {arguments.base_ref} resolved to {base_payload['base_sha']}; the contract requires the fixed Slice Base"
        )
    for group in ("B-on", "B-off"):
        destination = paths.proxy / group
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(paths.base_src, destination)
    print(f"product_base_sha={base_payload['base_sha']} files={base_payload['file_count']}")

    update_manifest(
        paths,
        run_id=run_id,
        created_at=manifest.get("created_at") or utc_now(),
        tool=tool_identity(),
        product_base=base_payload,
        groups=list(GROUPS),
        ports=ports,
    )

    container = JellyfinContainer(
        name=container_name,
        run_id=run_id,
        paths=paths,
        ports=ports,
    )
    gateway = environment.docker_gateway(container.name)
    container.gateway = gateway
    print(f"container={container.name} gateway={gateway}")
    container.create()

    info = wait_for_jellyfin(container)
    print(f"jellyfin_version={info.get('Version')} server_id={info.get('Id')}")

    if lock_payload is None:
        image = image_inspect(reference)
        lock_payload = build_lock(image, info, ports)
        write_json(paths.lock, lock_payload, mode=0o600)
        print(f"created server.lock.json digest={lock_payload['image_digest']}")
    else:
        if not str(info.get("Version", "")).startswith(str(lock_payload["server_version"])):
            raise ValidationError(
                f"running server version {info.get('Version')} != locked {lock_payload['server_version']}"
            )
        if lock_payload.get("server_id") and info.get("Id") and lock_payload["server_id"] != info.get("Id"):
            raise ValidationError("running server id differs from the locked server id; refusing to mix environments")

    media = MediaServer(paths.webroot, ports["media"], hosts=origin_hosts(gateway))
    try:
        ensure_directory(paths.webroot, 0o755)
        fixtures.generate_media(paths, container)
        media.start()
        try:
            credentials = fixtures.bootstrap_server(
                container,
                paths,
                gateway=gateway,
                media_port=ports["media"],
            )
            for entry in fixtures.MEDIA_LAYOUT:
                if entry["kind"] != "strm":
                    continue
                target = entry.get("target") or ""
                value = fixtures.remote_url(paths, gateway, ports["media"], target)
                fixtures.write_strm(paths, entry["key"], value)
            # the first dynamic* state is remote; later transitions are scenario-driven
            fixtures.write_strm(paths, "dynamic", fixtures.remote_url(paths, gateway, ports["media"], "remote-a.mp4"))
            library = fixtures.ensure_library(
                container,
                credentials,
                paths,
                gateway=gateway,
                media_port=ports["media"],
            )
            catalog = fixtures.item_catalog(container, credentials)
            fixtures.write_fixture_manifest(paths, catalog, credentials)
        finally:
            media.stop()
    except ValidationError:
        print("prepare failed; leaving the owned container in place for inspection (run `stop`)", file=sys.stderr)
        raise

    inventory = fixtures.media_inventory(paths, gateway, ports["media"])
    write_json(paths.evidence / "media-inventory.json", inventory, mode=0o600)
    update_manifest(
        paths,
        jellyfin={
            "container": container.name,
            "gateway": gateway,
            "image_reference": lock_payload["image_reference"],
            "image_digest": lock_payload["image_digest"],
        },
        runtime_version={
            "server_version": info.get("Version"),
            "server_id": info.get("Id"),
            "server_name": info.get("ServerName"),
        },
        library=library,
        fixtures=catalog,
        credentials_sha256=common.sha256_file(paths.credentials),
        media_inventory_sha256=common.sha256_file(paths.evidence / "media-inventory.json"),
    )
    write_text(
        paths.evidence / "prepare.json",
        json.dumps(
            {
                "prepared_at": utc_now(),
                "run_id": run_id,
                "ports": ports,
                "library": library,
                "item_ids": {key: value["id"] for key, value in catalog.items()},
                "server_version": info.get("Version"),
                "image_digest": lock_payload["image_digest"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        mode=0o600,
    )
    print("prepare complete")
    return 0


def origin_hosts(gateway: str) -> tuple[str, ...]:
    """Loopback for the validation client, bridge gateway for the container."""

    hosts = ["127.0.0.1"]
    if gateway and gateway not in hosts:
        hosts.append(gateway)
    return tuple(hosts)


def _container_name(run_id: str) -> str:
    import re

    safe = re.sub(r"[^a-z0-9_.-]", "-", run_id.casefold())[:48]
    return f"s1-jellyfin-{safe}"


def run_command_is_owned(container_name: str) -> bool:
    """True only when the existing container carries this tool's label."""

    completed = environment.run_command(
        ["docker", "inspect", "-f", '{{index .Config.Labels "jellyfinproxy.s1.validation"}}', container_name],
        check=False,
    )
    return completed.returncode == 0 and completed.stdout.strip() == "1"


# ---------------------------------------------------------------------------
# baseline
# ---------------------------------------------------------------------------


def command_baseline(arguments: argparse.Namespace) -> int:
    paths = RunPaths(root=arguments.run_dir.resolve())
    assert_owned_run_dir(paths)
    # Argument validation happens before any environment inspection so an
    # invalid selection can never be mistaken for a missing environment.
    cases = _parse_cases(arguments.cases)
    groups = [group.strip() for group in arguments.groups.split(",") if group.strip()]
    unknown = [group for group in groups if group not in GROUPS]
    if unknown:
        raise ValidationError(f"unknown groups {unknown}")
    manifest = load_manifest(paths)
    _cleanup_stale_owned_processes(paths, manifest)
    if not paths.lock.exists():
        raise ValidationError("prepare has not locked a server build yet; run `prepare` first")
    lock = read_json(paths.lock)
    ports = dict(manifest.get("ports") or {})
    missing_ports = [name for name in DEFAULT_PORTS if name not in ports]
    if missing_ports:
        raise ValidationError(f"manifest is missing ports {missing_ports}; re-run prepare")

    cases = _parse_cases(arguments.cases)
    groups = [group.strip() for group in arguments.groups.split(",") if group.strip()]
    unknown = [group for group in groups if group not in GROUPS]
    if unknown:
        raise ValidationError(f"unknown groups {unknown}")

    container = JellyfinContainer(
        name=(manifest.get("jellyfin") or {}).get("container") or _container_name(manifest.get("run_id", paths.root.name)),
        run_id=manifest.get("run_id", paths.root.name),
        paths=paths,
        ports=ports,
        gateway=(manifest.get("jellyfin") or {}).get("gateway", ""),
    )
    if not container.exists():
        raise ValidationError(
            f"owned container {container.name} no longer exists (it was removed by `stop`); run `prepare` again before `baseline`"
        )
    container.start()
    info = wait_for_jellyfin(container)
    if not str(info.get("Version", "")).startswith(str(lock.get("server_version", ""))):
        raise ValidationError(
            f"running server {info.get('Version')} does not match locked {lock.get('server_version')}"
        )

    credentials = _load_credentials(paths)
    catalog = fixtures.item_catalog(container, credentials)
    fixtures.write_fixture_manifest(paths, catalog, credentials)

    recorder = ResultRecorder(paths)
    supervisor = ProcessSupervisor(paths)
    origin = MediaServer(paths.webroot, ports["media"], hosts=origin_hosts(container.gateway))
    restart_state: dict[str, int] = {}
    started_at = utc_now()

    def origin_snapshot() -> list[dict[str, Any]]:
        return origin.state.snapshot()

    observatory_process = None
    try:
        ensure_directory(paths.webroot, 0o755)
        # A baseline transaction ledger must describe exactly this execution, so
        # any ledger left by an interrupted earlier attempt is moved aside first.
        ledger = paths.observatory / "observatory.jsonl"
        if ledger.exists():
            ledger.replace(paths.observatory / f"observatory.previous-{utc_now().replace(':', '')}.jsonl")
        origin.start()
        observatory_process = launch_observatory(
            supervisor,
            paths,
            port=ports["observatory"],
            target_url=container.base_url,
        )
        update_manifest(paths, tool_processes=supervisor.registrations())
        contexts: list[GroupContext] = []
        for group in groups:
            if group == "J":
                base_url = f"http://127.0.0.1:{ports['observatory']}"
                proxy_port = None
            else:
                cache_enabled = group == "B-on"
                plan = launch_proxy(
                    supervisor,
                    paths,
                    group=group,
                    port=ports["proxy_b_on"] if group == "B-on" else ports["proxy_b_off"],
                    upstream_url=f"http://127.0.0.1:{ports['observatory']}",
                    cache_enabled=cache_enabled,
                )
                append_proxy_process(paths, {"group": group, "pid": plan.process.pid, "config": str(plan.config_path)})
                base_url = f"http://127.0.0.1:{ports['proxy_b_on'] if group == 'B-on' else ports['proxy_b_off']}"
                proxy_port = ports["proxy_b_on"] if group == "B-on" else ports["proxy_b_off"]
            context = GroupContext(
                group=group,
                base_url=base_url,
                proxy_port=proxy_port,
                observatory_port=ports["observatory"],
                credentials=credentials,
                catalog=catalog,
                paths=paths,
                gateway=container.gateway,
                media_port=ports["media"],
                recorder=recorder,
                jellyfin=container,
                restarts=restart_state,
                process_management={"container": container, "restarts": restart_state},
            )
            context.origin_snapshot = origin_snapshot  # type: ignore[attr-defined]
            # Client requests must reach the observatory; it re-encodes nothing and
            # forwards identity representations so stored bytes match delivered bytes.
            contexts.append(context)

        any_failed = False
        for context in contexts:
            set_observatory_group(ports["observatory"], context.group)
            _scroll_origin(origin)
            print(f"-- group {context.group} base_url={context.base_url}")
            for case in cases:
                print(f"   case {case} start {utc_now()}", flush=True)
                if case == "RJ-06":
                    # reset the dynamic fixture to a known valid state before the case
                    _set_strm_and_refresh(context, context.remote_url("remote-a.mp4"))
                try:
                    run_cases(context, [case])
                except ValidationError as exc:
                    recorder.record(case, context.group, "runner", "BLOCKED", notes=[str(exc)])
                    any_failed = True
                except Exception as exc:  # noqa: BLE001 - a scenario failure must not skip stop
                    recorder.record(case, context.group, "runner", "FAIL", notes=[f"{type(exc).__name__}: {exc}"])
                    any_failed = True
            if any(
                entry.get("group") == context.group and entry.get("status") != "PASS"
                for entry in recorder.results().values()
            ):
                any_failed = True

        results = recorder.results()
        _export_transactions(paths, groups)
        _export_comparison(paths, results)
        write_json(paths.evidence / "results.json", results, mode=0o600)
        write_json(
            paths.evidence / "baseline.json",
            {
                "started_at": started_at,
                "finished_at": utc_now(),
                "cases": cases,
                "groups": groups,
                "manifest_tool_head": (manifest.get("tool") or {}).get("tool_head"),
                "server_version": info.get("Version"),
                "case_status": evidence.case_status(results),
            },
            mode=0o600,
        )
        _write_summary(paths, results, recorder, cases, groups)
        return 1 if any_failed else 0
    finally:
        # Stop order matters only for cleanup; failures above must not skip it.
        actions = supervisor.stop_all()
        origin.stop()
        update_manifest(paths, tool_processes=supervisor.registrations())
        if actions:
            write_json(
                paths.evidence / "baseline-stop.json",
                {"stopped_at": utc_now(), "actions": actions},
                mode=0o600,
            )


def _export_transactions(paths: RunPaths, groups: Sequence[str]) -> None:
    """Export the redacted upstream transaction ledger per control group.

    The observatory already redacts headers and stores only digests of bodies and
    media, so this is a split of the run ledger, not a new copy of raw traffic.
    """

    source = paths.observatory / "observatory.jsonl"
    if not source.exists():
        return
    counters: dict[str, int] = {group: 0 for group in groups}
    handles = {
        group: (paths.evidence / f"transactions-{group}.jsonl").open("w", encoding="utf-8")
        for group in groups
    }
    try:
        with source.open("r", encoding="utf-8") as input_handle:
            for line in input_handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                group = record.get("group")
                handle = handles.get(str(group))
                if handle is None:
                    continue
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
                counters[str(group)] += 1
    finally:
        for handle in handles.values():
            handle.close()
    print("transactions=" + json.dumps(counters))


def _export_comparison(paths: RunPaths, results: Mapping[str, Mapping[str, Any]]) -> None:
    """Write the cross-group difference report required by the contract."""

    by_case: dict[str, dict[str, Any]] = {}
    for entry in results.values():
        case = str(entry.get("case"))
        group = str(entry.get("group"))
        by_case.setdefault(case, {})[group] = {
            "status": entry.get("status"),
            "detail": entry.get("detail"),
            "notes": entry.get("notes"),
        }
    write_json(paths.evidence / "comparison.json", by_case, mode=0o600)


def _cleanup_stale_owned_processes(paths: RunPaths, manifest: Mapping[str, Any]) -> None:
    """Terminate proxy processes an earlier interrupted run left behind.

    Ownership is re-verified through the run directory (cwd/cmdline) so a pid
    recycled by the OS is never touched.
    """

    for entry in manifest.get("proxy_processes") or []:
        pid = entry.get("pid")
        if not isinstance(pid, int) or pid <= 0:
            continue
        if not environment._pid_alive(pid):
            continue
        if not environment._pid_matches_run(pid, paths):
            raise ValidationError(
                f"pid {pid} from a previous run is alive but no longer belongs to {paths.root}; refusing to continue"
            )
        environment._terminate(pid)
        print(f"cleaned up stale proxy pid={pid}")
    environment.update_manifest(paths, proxy_processes=[])


def _scroll_origin(origin: MediaServer) -> None:
    # The origin keeps all requests for RJ-08 lifecycle evidence; nothing to reset.
    return None


def _parse_cases(value: str) -> list[str]:
    if not value.strip():
        return list(REQUIRED_CASES)
    requested = [part.strip().upper() for part in value.split(",") if part.strip()]
    unknown = [case for case in requested if case not in SCENARIOS]
    if unknown:
        raise ValidationError(f"unknown cases {unknown}; valid: {sorted(SCENARIOS)}")
    return requested


def _load_credentials(paths: RunPaths) -> Any:
    if not paths.credentials.exists():
        raise ValidationError(f"missing credentials at {paths.credentials}; run `prepare` first")
    payload = read_json(paths.credentials)
    return fixtures.Credentials(
        admin_name=payload["admin_name"],
        admin_password=payload["admin_password"],
        admin_token=payload["admin_token"],
        users=payload["users"],
    )


def _write_summary(
    paths: RunPaths,
    results: Mapping[str, Mapping[str, Any]],
    recorder: ResultRecorder,
    cases: Sequence[str],
    groups: Sequence[str],
) -> None:
    lines = ["# S1.1 real Jellyfin 12.3 baseline summary", ""]
    lines.append(f"- generated: {utc_now()}")
    lines.append(f"- cases: {', '.join(cases)}")
    lines.append(f"- groups: {', '.join(groups)}")
    lines.append("")
    lines.append("| case | group | sub-case | status |")
    lines.append("|---|---|---|---|")
    for key in sorted(results):
        entry = results[key]
        lines.append(
            f"| {entry.get('case')} | {entry.get('group')} | {entry.get('subcase')} | {entry.get('status')} |"
        )
    lines.append("")
    counts: dict[str, int] = {}
    for entry in results.values():
        status = entry.get("status", "?")
        counts[status] = counts.get(status, 0) + 1
    lines.append("Totals: " + ", ".join(f"{status}={count}" for status, count in sorted(counts.items())))
    write_text(paths.evidence / "summary.md", "\n".join(lines) + "\n", mode=0o600)


# ---------------------------------------------------------------------------
# stop
# ---------------------------------------------------------------------------


def command_stop(arguments: argparse.Namespace) -> int:
    paths = RunPaths(root=arguments.run_dir.resolve())
    stop_path = paths.evidence / "stop.json"
    previous = read_json(stop_path) if stop_path.exists() else None
    result = stop_run(paths, keep_files=not arguments.remove_files)
    result["idempotent_repeat"] = previous is not None
    result["commands"] = ["doctor", "prepare", "baseline", "stop", "verify-evidence"]
    if not arguments.remove_files:
        ensure_directory(paths.evidence, 0o700)
        # The first stop record is the evidence of what was actually running;
        # later calls only append to the history so re-running stays idempotent
        # without erasing the original observation.
        if previous is None:
            write_json(stop_path, result, mode=0o600)
        with (paths.evidence / "stop-history.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
    for action in result["actions"]:
        print(f"- {action}")
    return 0


# ---------------------------------------------------------------------------
# verify-evidence
# ---------------------------------------------------------------------------


def command_verify(arguments: argparse.Namespace) -> int:
    paths = RunPaths(root=arguments.run_dir.resolve())
    cases = _parse_cases(arguments.cases) if arguments.cases.strip() else list(REQUIRED_CASES)
    report = evidence.verify(paths, expected_cases=cases)
    evidence.report_to_console(report)
    return 0 if not report.failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
