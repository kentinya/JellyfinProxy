"""Shared primitives for the real Jellyfin 12.3 validation tool.

Everything here is test tooling: it never participates in proxy behaviour and
must never be imported by ``main.py`` or any product module.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

#: Ports used by the contract. Only loopback is bound by the tool.
DEFAULT_PORTS: dict[str, int] = {
    "jellyfin": 18096,
    "observatory": 18097,
    "proxy_b_on": 18098,
    "proxy_b_off": 18099,
    "media": 18100,
}

#: Fixed product sources for the B-on / B-off control groups.
PRODUCT_BASE = "6bec0d64c5b5f50c74dcf76cc679185e5f1ebec5"

#: Server version the contract requires; anything else is refused.
REQUIRED_SERVER_VERSION = "12.3"

RUN_MARKER = ".s1-validation-run"
RUN_MARKER_LABEL = "jellyfinproxy.s1.validation"
DOCKER_LABEL = "jellyfinproxy.s1.validation"


class ValidationError(RuntimeError):
    """Raised for any condition that must abort the requested command."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


REDACTED = "[REDACTED]"
_SENSITIVE_KEYS = {
    "access_token",
    "accesstoken",
    "token",
    "pw",
    "password",
    "api_key",
    "apikey",
    "x-emby-token",
    "x-emby-authorization",
    "authorization",
    "cookie",
    "secret",
}
_SECRET_QUERY = re.compile(r"(?i)\b(api_key|apikey|x-emby-token|access_token|token|apiKey)=([^&\s\"']+)")
_MEDIABROWSER_TOKEN = re.compile(r"(?i)(MediaBrowser\s+[^,\"]*?Token=)([^,\"\s]+)")
_URL_CREDENTIAL = re.compile(r"(?i)\b(https?://)([^/\s:@]+):([^/\s@]+)@")


def redact_text(value: str) -> str:
    """Remove credentials from free text (headers, URLs, log lines)."""

    if not isinstance(value, str):
        return value
    value = _SECRET_QUERY.sub(lambda m: f"{m.group(1)}={REDACTED}", value)
    value = _MEDIABROWSER_TOKEN.sub(lambda m: f"{m.group(1)}{REDACTED}", value)
    value = _URL_CREDENTIAL.sub(lambda m: f"{m.group(1)}{REDACTED}@{m.group(3)}", value)
    return value


def redact(payload: Any) -> Any:
    """Return a copy of ``payload`` with credential-shaped values redacted.

    Signed media URLs are replaced by a digest marker so comparisons can still
    distinguish two different URLs without leaking the signature.
    """

    if isinstance(payload, Mapping):
        result: dict[str, Any] = {}
        for key, value in payload.items():
            if str(key).casefold() in _SENSITIVE_KEYS:
                result[key] = REDACTED
            else:
                result[key] = redact(value)
        return result
    if isinstance(payload, (list, tuple)):
        return [redact(item) for item in payload]
    if isinstance(payload, str):
        return redact_text(payload)
    return payload


def url_digest(url: str) -> str:
    return sha256_bytes(url.encode("utf-8"))[:16]


# ---------------------------------------------------------------------------
# process / docker helpers
# ---------------------------------------------------------------------------


def run_command(
    argv: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        list(argv),
        cwd=str(cwd) if cwd else None,
        env=dict(env) if env is not None else None,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if check and completed.returncode != 0:
        raise ValidationError(
            f"command failed ({completed.returncode}): {' '.join(argv)}\n"
            f"stdout: {completed.stdout.strip()}\nstderr: {completed.stderr.strip()}"
        )
    return completed


def port_is_free(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


def port_is_open(port: int, host: str = "127.0.0.1", timeout: float = 0.5) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(timeout)
        return probe.connect_ex((host, port)) == 0


def wait_for(predicate, *, timeout: float, interval: float = 0.5, description: str = "condition"):
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            result = predicate()
        except Exception as exc:  # noqa: BLE001 - probe errors are expected while starting
            last_error = exc
        else:
            if result:
                return result
        time.sleep(interval)
    raise ValidationError(f"timed out after {timeout}s waiting for {description}: {last_error}")


def write_private(path: Path, payload: bytes | str, mode: int = 0o600) -> None:
    """Write a file that may contain credentials, with restrictive permissions."""

    path.parent.mkdir(parents=True, exist_ok=True)
    data = payload.encode("utf-8") if isinstance(payload, str) else payload
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.chmod(tmp, mode)
    tmp.replace(path)


def write_text(path: Path, payload: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    os.chmod(path, mode)


def write_json(path: Path, payload: Any, mode: int = 0o644) -> None:
    write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", mode)


def read_json(path: Path) -> Any:
    with path.open("rb") as handle:
        return json.load(handle)


def ensure_directory(path: Path, mode: int = 0o700) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, mode)
    return path


def remove_tree(path: Path) -> None:
    if not path.exists():
        return
    shutil.rmtree(path, ignore_errors=True)


def python_executable() -> str:
    return sys.executable


def environment_fingerprint() -> dict[str, Any]:
    """Record interpreter and dependency versions for the evidence bundle."""

    def version_of(module_name: str) -> str | None:
        try:
            module = __import__(module_name)
        except Exception:  # noqa: BLE001 - missing optional dependency is recorded as None
            return None
        return getattr(module, "__version__", "unknown")

    return {
        "python": sys.version.split()[0],
        "python_executable": sys.executable,
        "platform": sys.platform,
        "fastapi": version_of("fastapi"),
        "httpx": version_of("httpx"),
        "uvicorn": version_of("uvicorn"),
        "pytest": version_of("pytest"),
    }


@dataclass
class CommandRecord:
    command: str
    started_at: str
    finished_at: str
    exit_code: int
    duration_seconds: float
    counts: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "command": redact_text(self.command),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "exit_code": self.exit_code,
            "duration_seconds": round(self.duration_seconds, 3),
            "counts": self.counts,
            "notes": self.notes,
        }


def dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered
