"""Isolated environment lifecycle for the real Jellyfin 12.3 baseline.

Everything created here is namespaced by the run directory and a docker label so
that ``stop`` can only ever remove resources this tool created.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from scripts.validation.common import (
    DEFAULT_PORTS,
    PRODUCT_BASE,
    REQUIRED_SERVER_VERSION,
    RUN_MARKER,
    RUN_MARKER_LABEL,
    ValidationError,
    ensure_directory,
    port_is_free,
    port_is_open,
    read_json,
    remove_tree,
    run_command,
    sha256_file,
    utc_now,
    wait_for,
    write_json,
)

JELLYFIN_IMAGE_ENV = "S1_JELLYFIN_IMAGE"
OFFICIAL_REPOSITORY = "jellyfin/jellyfin"
REQUIRED_PRODUCT_FILES = (
    "main.py",
    "config.py",
    "version.py",
    "requirements.txt",
    "handlers",
    "services",
    "policies",
    "routers",
    "infrastructure",
)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def git_output(*args: str) -> str:
    completed = run_command(["git", *args], cwd=repo_root())
    return completed.stdout.strip()


def git_rev(rev: str = "HEAD") -> str:
    return git_output("rev-parse", rev)


# ---------------------------------------------------------------------------
# run directory
# ---------------------------------------------------------------------------


@dataclass
class RunPaths:
    root: Path

    @property
    def private(self) -> Path:
        return self.root / "private"

    @property
    def evidence(self) -> Path:
        return self.root / "evidence"

    @property
    def manifest(self) -> Path:
        return self.root / "manifest.json"

    @property
    def lock(self) -> Path:
        return self.root / "server.lock.json"

    @property
    def marker(self) -> Path:
        return self.root / RUN_MARKER

    @property
    def credentials(self) -> Path:
        return self.private / "credentials.json"

    @property
    def jellyfin(self) -> Path:
        return self.root / "jellyfin"

    @property
    def media(self) -> Path:
        return self.root / "media"

    @property
    def webroot(self) -> Path:
        return self.root / "webroot"

    @property
    def base_src(self) -> Path:
        return self.root / "base-src"

    @property
    def proxy(self) -> Path:
        return self.root / "proxy"

    @property
    def observatory(self) -> Path:
        return self.root / "observatory"

    def rel(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.root))
        except ValueError:
            return str(path)


def privileged_umask_ok() -> None:
    old = os.umask(0o077)
    os.umask(old)


def prepare_run_dir(run_dir: Path) -> RunPaths:
    paths = RunPaths(root=run_dir.resolve())
    ensure_directory(paths.root, 0o700)
    ensure_directory(paths.private, 0o700)
    ensure_directory(paths.evidence, 0o700)
    marker = {
        "label": RUN_MARKER_LABEL,
        "run_dir": str(paths.root),
        "created_at": utc_now(),
        "tool": "scripts/validate_jellyfin_12_3.py",
    }
    write_json(paths.marker, marker, mode=0o600)
    return paths


def assert_owned_run_dir(paths: RunPaths) -> None:
    if not paths.marker.exists():
        raise ValidationError(
            f"{paths.root} has no {RUN_MARKER} marker; refusing to operate on a directory this tool did not create"
        )
    marker = read_json(paths.marker)
    if marker.get("label") != RUN_MARKER_LABEL:
        raise ValidationError(f"{paths.marker} does not carry the expected ownership label")


# ---------------------------------------------------------------------------
# ports
# ---------------------------------------------------------------------------


def resolve_ports(
    preferred: Mapping[str, int] | None = None,
    *,
    owned: Iterable[int] = (),
) -> dict[str, int]:
    """Assign loopback ports, failing explicitly instead of stealing one.

    ``owned`` lists ports already published by this run's own container; those
    are reusable on a repeated ``prepare`` and never treated as foreign.
    """

    chosen: dict[str, int] = {}
    owned_set = set(owned)
    requested = dict(DEFAULT_PORTS)
    if preferred:
        requested.update({key: int(value) for key, value in preferred.items()})
    for name, port in requested.items():
        if port not in owned_set and not port_is_free(port):
            raise ValidationError(
                f"port {port} for {name} is already in use; refusing to take over an existing service"
            )
        chosen[name] = port
    if len(set(chosen.values())) != len(chosen):
        raise ValidationError("resolved ports are not unique")
    return chosen


def port_owner_hint(port: int) -> str:
    try:
        completed = subprocess.run(
            ["ss", "-ltnp", f"sport = :{port}"], capture_output=True, text=True, timeout=5
        )
    except Exception:  # noqa: BLE001 - diagnostics only
        return "unknown"
    text = completed.stdout.strip()
    return text.splitlines()[-1] if text else "not listening"


# ---------------------------------------------------------------------------
# docker
# ---------------------------------------------------------------------------


def docker_available() -> tuple[bool, str]:
    try:
        completed = run_command(["docker", "version", "--format", "{{.Client.Version}} {{.Server.Version}}"])
    except (ValidationError, FileNotFoundError) as exc:
        return False, str(exc)
    return True, completed.stdout.strip()


def docker_compose_version() -> str | None:
    try:
        completed = run_command(["docker", "compose", "version", "--short"])
    except ValidationError:
        return None
    return completed.stdout.strip() or None


def image_reference() -> str:
    configured = os.environ.get(JELLYFIN_IMAGE_ENV)
    if configured:
        return configured
    return f"{OFFICIAL_REPOSITORY}:{REQUIRED_SERVER_VERSION}"


def pull_image(reference: str) -> None:
    run_command(["docker", "pull", reference], timeout=1800)


def image_inspect(reference: str) -> dict[str, Any]:
    completed = run_command(["docker", "image", "inspect", reference])
    data = json.loads(completed.stdout)[0]
    labels = (data.get("Config", {}).get("Labels") or {})
    return {
        "reference": reference,
        "id": data.get("Id"),
        "repo_digests": data.get("RepoDigests") or [],
        "os": data.get("Os"),
        "architecture": data.get("Architecture"),
        "created": data.get("Created"),
        "labels": {
            key: labels.get(key)
            for key in (
                "org.opencontainers.image.version",
                "org.opencontainers.image.source",
                "org.opencontainers.image.documentation",
            )
            if key in labels
        },
    }


def image_present(reference: str) -> bool:
    completed = run_command(["docker", "image", "inspect", reference], check=False)
    return completed.returncode == 0


def _container_name(run_id: str) -> str:
    safe = re.sub(r"[^a-z0-9_.-]", "-", run_id.casefold())[:48]
    return f"s1-jellyfin-{safe}"


def _owned_containers() -> list[dict[str, str]]:
    completed = run_command(
        ["docker", "ps", "-a", "--filter", f"label={RUN_MARKER_LABEL}", "--format", "{{.Names}}\t{{.Label \"jellyfinproxy.s1.run\"}}\t{{.Status}}"]
    )
    containers: list[dict[str, str]] = []
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        containers.append(
            {
                "name": parts[0],
                "run": parts[1] if len(parts) > 1 else "",
                "status": parts[2] if len(parts) > 2 else "",
            }
        )
    return containers


@dataclass
class JellyfinContainer:
    name: str
    run_id: str
    paths: RunPaths
    ports: dict[str, int]

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.ports['jellyfin']}"

    @property
    def internal_base_url(self) -> str:
        # Jellyfin reaches the host-bound media origin through the docker gateway.
        return f"http://{self.gateway}:{self.ports['media']}"

    gateway: str = ""

    def exists(self) -> bool:
        completed = run_command(["docker", "inspect", self.name], check=False)
        return completed.returncode == 0

    def running(self) -> bool:
        completed = run_command(
            ["docker", "inspect", "-f", "{{.State.Running}}", self.name], check=False
        )
        return completed.returncode == 0 and completed.stdout.strip() == "true"

    def create(self) -> None:
        if self.exists():
            if self.running():
                return
            run_command(["docker", "start", self.name])
            return
        self.gateway = docker_gateway(self.name)
        command = [
            "docker",
            "run",
            "-d",
            "--name",
            self.name,
            "--label",
            f"{RUN_MARKER_LABEL}=1",
            "--label",
            f"jellyfinproxy.s1.run={self.run_id}",
            "-p",
            f"127.0.0.1:{self.ports['jellyfin']}:8096",
            "--add-host",
            f"host.docker.internal:host-gateway",
            "-v",
            f"{self.paths.jellyfin / 'config'}:/config",
            "-v",
            f"{self.paths.jellyfin / 'cache'}:/cache",
            "-v",
            f"{self.paths.media}:/media",
            os.environ.get(JELLYFIN_IMAGE_ENV) or image_reference(),
        ]
        run_command(command)

    def start(self) -> None:
        if self.exists() and not self.running():
            run_command(["docker", "start", self.name])

    def stop(self) -> None:
        if self.exists() and self.running():
            run_command(["docker", "stop", "-t", "20", self.name])

    def remove(self) -> None:
        if self.exists():
            run_command(["docker", "rm", "-f", self.name])

    def logs(self, since: str = "30m") -> str:
        completed = run_command(["docker", "logs", "--since", since, self.name], check=False)
        return completed.stdout + completed.stderr

    def server_version(self) -> str | None:
        try:
            completed = run_command(
                ["curl", "-fsS", "--max-time", "10", f"{self.base_url}/System/Info/Public"],
                check=False,
            )
        except FileNotFoundError:
            return None
        if completed.returncode != 0:
            return None
        try:
            return json.loads(completed.stdout).get("Version")
        except ValueError:
            return None


def docker_gateway(container_name: str) -> str:
    """Determine the host address reachable from the container's bridge network."""

    if port_is_open(0, "127.0.0.1", timeout=0.01):
        pass
    for candidate in ("172.17.0.1", "172.18.0.1", "172.19.0.1", "172.20.0.1"):
        if _host_reachable_from_bridge(candidate):
            return candidate
    raise ValidationError(
        "cannot determine a docker bridge gateway address; the media origin would not be reachable from Jellyfin"
    )


def _host_reachable_from_bridge(candidate: str) -> bool:
    completed = run_command(["ip", "-o", "-4", "addr", "show"], check=False)
    return f" {candidate}/" in completed.stdout


def container_host_ports(name: str) -> dict[int, int]:
    """Host ports published by an already-created container (ownership check)."""

    completed = run_command(
        ["docker", "inspect", "-f", "{{json .HostConfig.PortBindings}}", name], check=False
    )
    if completed.returncode != 0:
        return {}
    try:
        bindings = json.loads(completed.stdout)
    except ValueError:
        return {}
    ports: dict[int, int] = {}
    for container_port, host_bindings in (bindings or {}).items():
        container_number = int(str(container_port).split("/", 1)[0])
        for binding in host_bindings or []:
            try:
                ports[int(binding["HostPort"])] = container_number
            except (KeyError, TypeError, ValueError):
                continue
    return ports


def wait_for_jellyfin(container: JellyfinContainer, *, timeout: float = 300) -> dict[str, Any]:
    """Wait for a fully initialised 12.3 server, not merely an open socket.

    Jellyfin binds the port first, then reports an empty Version, then serves
    /Startup/User, and only after that accepts authenticated calls. Calling the
    API during those phases produces resets, so both gates are required here.
    """

    def _ready() -> dict[str, Any] | None:
        completed = run_command(
            ["curl", "-fsS", "--max-time", "5", f"{container.base_url}/System/Info/Public"],
            check=False,
        )
        if completed.returncode != 0:
            return None
        try:
            info = json.loads(completed.stdout)
        except ValueError:
            return None
        # Kestrel starts listening before the server finishes initialising and
        # then reports an empty Version; only a populated version counts.
        if not str(info.get("Version") or "").strip():
            return None
        # The API is only usable after the startup wizard phase:
        #   incomplete wizard -> /Startup/User answers 200
        #   completed wizard -> /Startup/User is protected (401) and /Users/Public works
        probe = "/Users/Public" if info.get("StartupWizardCompleted") else "/Startup/User"
        startup = run_command(
            ["curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "5",
             f"{container.base_url}{probe}"],
            check=False,
        )
        if startup.stdout.strip() != "200":
            return None
        return info

    info = wait_for(_ready, timeout=timeout, interval=2, description="Jellyfin /System/Info/Public")
    version = str(info.get("Version") or "")
    if not version.startswith(REQUIRED_SERVER_VERSION):
        raise ValidationError(
            f"running Jellyfin reports version {version!r}; the contract requires {REQUIRED_SERVER_VERSION}"
        )
    return info


# ---------------------------------------------------------------------------
# server lock
# ---------------------------------------------------------------------------


def build_lock(image: dict[str, Any], info: Mapping[str, Any], ports: Mapping[str, int]) -> dict[str, Any]:
    digest = None
    for repo_digest in image.get("repo_digests") or []:
        if "@sha256:" in repo_digest:
            digest = repo_digest.split("@", 1)[1]
            break
    if digest is None:
        raise ValidationError("official image has no repo digest; refusing to create an unlocked environment")
    return {
        "format": 1,
        "created_at": utc_now(),
        "image_reference": image.get("reference"),
        "image_digest": digest,
        "image_id": image.get("id"),
        "image_repo_digests": image.get("repo_digests"),
        "image_architecture": image.get("architecture"),
        "image_os": image.get("os"),
        "image_labels": image.get("labels"),
        "server_version": str(info.get("Version")),
        "server_id": info.get("Id"),
        "server_name": info.get("ServerName"),
        "required_server_version": REQUIRED_SERVER_VERSION,
        "ports": dict(ports),
        "product_base": PRODUCT_BASE,
    }


def verify_lock(lock: Mapping[str, Any], *, reference: str) -> None:
    if lock.get("required_server_version") != REQUIRED_SERVER_VERSION:
        raise ValidationError("lock file was produced for a different required server version")
    # Compare the major.minor series, so 12.3.x is accepted and 12.4/13.0 is not.
    recorded = str(lock.get("server_version") or "")
    series = ".".join(recorded.split(".")[:2])
    if series != REQUIRED_SERVER_VERSION:
        raise ValidationError(
            f"lock server_version {recorded!r} does not satisfy the {REQUIRED_SERVER_VERSION} contract"
        )
    if lock.get("product_base") != PRODUCT_BASE:
        raise ValidationError(
            "lock product_base does not match the contract's fixed Slice Base; refusing to mix controls"
        )
    if lock.get("image_reference") != reference:
        raise ValidationError(
            f"lock image reference {lock.get('image_reference')!r} != requested {reference!r}"
        )
    if not lock.get("image_digest"):
        raise ValidationError("lock file has no image digest")


# ---------------------------------------------------------------------------
# product source extraction
# ---------------------------------------------------------------------------


def extract_base_source(base_ref: str, destination: Path) -> dict[str, Any]:
    """Extract the fixed product sources with ``git archive`` (never the worktree)."""

    if destination.exists():
        remove_tree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination.parent / "base-source.tar"
    run_command(["git", "archive", "--format=tar", "-o", str(archive), base_ref], cwd=repo_root())
    run_command(["tar", "-xf", str(archive), "-C", str(destination)])
    archive.unlink()
    sha = git_rev(base_ref)
    digests = {}
    for relative in REQUIRED_PRODUCT_FILES:
        target = destination / relative
        if target.is_dir():
            for path in sorted(target.rglob("*.py")):
                digests[str(path.relative_to(destination))] = sha256_file(path)
        elif target.is_file():
            digests[relative] = sha256_file(target)
    write_json(destination / "SOURCE_IDENTITY.json", {"base_ref": base_ref, "base_sha": sha, "files": digests})
    return {"base_ref": base_ref, "base_sha": sha, "file_count": len(digests), "files": digests}


# ---------------------------------------------------------------------------
# stop
# ---------------------------------------------------------------------------


def stop_run(paths: RunPaths, *, keep_files: bool = True) -> dict[str, Any]:
    """Stop only resources recorded as owned by this run directory."""

    assert_owned_run_dir(paths)
    actions: list[str] = []
    manifest = read_json(paths.manifest) if paths.manifest.exists() else {}
    run_id = manifest.get("run_id", paths.root.name)
    container_name = manifest.get("jellyfin", {}).get("container") or _container_name(run_id)
    if run_command(["docker", "inspect", container_name], check=False).returncode == 0:
        labels = run_command(
            ["docker", "inspect", "-f", "{{index .Config.Labels \"jellyfinproxy.s1.validation\"}}", container_name],
            check=False,
        ).stdout.strip()
        if labels == "1":
            run_command(["docker", "rm", "-f", container_name], check=False)
            actions.append(f"removed container {container_name}")
        else:
            actions.append(f"left container {container_name} in place (label mismatch)")
    else:
        actions.append("no owned container present")

    for process in manifest.get("proxy_processes", []):
        pid = process.get("pid")
        if isinstance(pid, int) and pid > 0 and _pid_alive(pid):
            if _pid_matches_run(pid, paths):
                _terminate(pid)
                actions.append(f"stopped proxy pid {pid}")
            else:
                actions.append(f"left pid {pid} running (ownership mismatch)")
    for process in manifest.get("tool_processes", []):
        pid = process.get("pid")
        if isinstance(pid, int) and pid > 0 and _pid_alive(pid):
            _terminate(pid)
            actions.append(f"stopped tool process pid {pid}")

    if not keep_files:
        remove_tree(paths.root)
        actions.append("removed run directory")
    return {"run_dir": str(paths.root), "actions": actions, "stopped_at": utc_now()}


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _pid_matches_run(pid: int, paths: RunPaths) -> bool:
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\x00", b" ").decode("utf-8", "replace")
        cwd = Path(f"/proc/{pid}/cwd").resolve()
    except OSError:
        return False
    return str(paths.root) in cwd.as_posix() or str(paths.root) in cmdline


def _terminate(pid: int, *, timeout: float = 10) -> None:
    import signal
    import time

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return
        time.sleep(0.2)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return


# ---------------------------------------------------------------------------
# manifest helpers
# ---------------------------------------------------------------------------


def load_manifest(paths: RunPaths) -> dict[str, Any]:
    if not paths.manifest.exists():
        raise ValidationError(f"no manifest at {paths.manifest}; run `prepare` first")
    return read_json(paths.manifest)


def update_manifest(paths: RunPaths, **fields: Any) -> dict[str, Any]:
    manifest = read_json(paths.manifest) if paths.manifest.exists() else {}
    manifest.update(fields)
    manifest["updated_at"] = utc_now()
    write_json(paths.manifest, manifest, mode=0o600)
    return manifest


def merge_manifest(paths: RunPaths, section: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    manifest = read_json(paths.manifest) if paths.manifest.exists() else {}
    current = dict(manifest.get(section) or {})
    current.update(payload)
    manifest[section] = current
    manifest["updated_at"] = utc_now()
    write_json(paths.manifest, manifest, mode=0o600)
    return manifest


def append_proxy_process(paths: RunPaths, entry: Mapping[str, Any]) -> dict[str, Any]:
    manifest = read_json(paths.manifest) if paths.manifest.exists() else {}
    processes = list(manifest.get("proxy_processes") or [])
    processes.append(dict(entry))
    manifest["proxy_processes"] = processes
    manifest["updated_at"] = utc_now()
    write_json(paths.manifest, manifest, mode=0o600)
    return manifest


def tool_identity() -> dict[str, Any]:
    """Identity of the validation tool itself (its own committed sources)."""

    head = git_rev("HEAD")
    status = run_command(["git", "status", "--porcelain", "--untracked-files=no"], cwd=repo_root()).stdout
    dirty_files = [line for line in status.splitlines() if line.strip()]
    tool_files = sorted(
        str(path.relative_to(repo_root()))
        for path in (repo_root() / "scripts").rglob("*.py")
    )
    tool_files.append("scripts/validate_jellyfin_12_3.py")
    untracked = run_command(
        ["git", "status", "--porcelain", "--", "scripts/validation"], cwd=repo_root()
    ).stdout
    digests = {}
    for relative in sorted(set(tool_files)):
        path = repo_root() / relative
        if path.is_file():
            digests[relative] = sha256_file(path)
    return {
        "tool_head": head,
        "dirty_tracked_files": dirty_files,
        "tool_files_sha256": digests,
        "tool_files_untracked": [line for line in untracked.splitlines() if line.strip()],
    }
