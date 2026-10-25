"""Controlled media origin used as the STRM target for real Jellyfin tests.

This is test infrastructure only. It serves bytes from the run directory,
supports Range requests, and can throttle or abort transfers so that stream
lifecycle observations (RJ-08) happen against real network behaviour.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from scripts.validation.common import sha256_file


@dataclass
class MediaRequest:
    timestamp: float
    method: str
    path: str
    range_header: str | None
    status: int
    bytes_sent: int
    aborted_by_client: bool
    finished: bool


@dataclass
class MediaServerState:
    requests: list[MediaRequest] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def record(self, entry: MediaRequest) -> None:
        with self.lock:
            self.requests.append(entry)

    def reset(self) -> None:
        with self.lock:
            self.requests.clear()

    def snapshot(self) -> list[dict[str, Any]]:
        with self.lock:
            return [
                {
                    "timestamp": round(item.timestamp, 3),
                    "method": item.method,
                    "path": item.path,
                    "range": item.range_header,
                    "status": item.status,
                    "bytes_sent": item.bytes_sent,
                    "aborted_by_client": item.aborted_by_client,
                    "finished": item.finished,
                }
                for item in self.requests
            ]


class _Handler(BaseHTTPRequestHandler):
    server_version = "S1MediaOrigin/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        # Keep the tool's stdout clean; requests are recorded structurally.
        return

    # -- helpers ---------------------------------------------------------
    @property
    def state(self) -> MediaServerState:
        return self.server.state  # type: ignore[attr-defined]

    @property
    def root(self) -> Path:
        return self.server.root  # type: ignore[attr-defined]

    def _resolve(self, url_path: str) -> tuple[Path, str] | None:
        parsed = urlparse(url_path)
        relative = parsed.path.lstrip("/")
        if not relative or ".." in Path(relative).parts:
            return None
        candidate = self.root / relative
        if not candidate.is_file():
            return None
        return candidate, parsed.path

    def _parse_range(self, header: str | None, size: int) -> tuple[int, int] | None:
        if not header:
            return None
        if not header.startswith("bytes="):
            return None
        spec = header[len("bytes=") :].split(",", 1)[0].strip()
        if "-" not in spec:
            return None
        start_text, _, end_text = spec.partition("-")
        try:
            if start_text == "":
                length = int(end_text)
                return max(size - length, 0), size - 1
            start = int(start_text)
            end = int(end_text) if end_text else size - 1
        except ValueError:
            return None
        if start >= size:
            return None
        return start, min(end, size - 1)

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib naming
        self._serve(head_only=True)

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        self._serve(head_only=False)

    def _serve(self, *, head_only: bool) -> None:
        resolved = self._resolve(self.path)
        parsed = urlparse(self.path)
        if resolved is None:
            self.state.record(
                MediaRequest(time.time(), self.command, parsed.path, self.headers.get("Range"), 404, 0, False, True)
            )
            self.send_response(HTTPStatus.NOT_FOUND)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        file_path, request_path = resolved
        size = file_path.stat().st_size
        query = parse_qs(parsed.query)
        throttle_bps = int(query.get("throttle", ["0"])[0] or 0)
        abort_after = int(query.get("abort_after", ["0"])[0] or 0)

        span = self._parse_range(self.headers.get("Range"), size)
        if span is None:
            start, end = 0, size - 1
            status = HTTPStatus.OK
        else:
            start, end = span
            status = HTTPStatus.PARTIAL_CONTENT
        length = end - start + 1 if size else 0

        entry = MediaRequest(time.time(), self.command, request_path, self.headers.get("Range"), int(status), 0, False, False)
        self.send_response(status)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if status is HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if head_only:
            entry.finished = True
            self.state.record(entry)
            return

        sent = 0
        chunk_size = 16 * 1024
        try:
            with file_path.open("rb") as handle:
                handle.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = handle.read(min(chunk_size, remaining))
                    if not chunk:
                        break
                    if abort_after and sent + len(chunk) >= abort_after:
                        self.wfile.write(chunk[: abort_after - sent])
                        sent = abort_after
                        self.wfile.flush()
                        entry.aborted_by_client = True
                        # Drop the connection mid-body to simulate a truncated origin.
                        self.close_connection = True
                        break
                    self.wfile.write(chunk)
                    sent += len(chunk)
                    remaining -= len(chunk)
                    if throttle_bps:
                        time.sleep(len(chunk) / throttle_bps)
            self.wfile.flush()
            entry.finished = True
        except (BrokenPipeError, ConnectionResetError):
            entry.aborted_by_client = True
        finally:
            entry.bytes_sent = sent
            self.state.record(entry)


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], root: Path, state: MediaServerState) -> None:
        super().__init__(address, _Handler)
        self.root = root
        self.state = state


class MediaServer:
    """Media origin bound to an explicit, documented set of host addresses.

    The validation client follows the proxy's ``Location`` address (loopback),
    while the Jellyfin container fetches the same STRM target through the docker
    bridge gateway. Both listeners serve the identical root and share one request
    ledger, so evidence always describes the same origin. No public interface is
    used, and the addresses are recorded in the manifest.
    """

    def __init__(self, root: Path, port: int, hosts: tuple[str, ...] = ("127.0.0.1",)) -> None:
        self.root = Path(root).resolve()
        self.port = port
        self.hosts = tuple(hosts) or ("127.0.0.1",)
        self.state = MediaServerState()
        self._servers: list[_Server] = []
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        if self._servers:
            return
        for host in self.hosts:
            server = _Server((host, self.port), self.root, self.state)
            thread = threading.Thread(
                target=server.serve_forever,
                name=f"s1-media-origin-{host}",
                daemon=True,
            )
            thread.start()
            self._servers.append(server)
            self._threads.append(thread)

    def stop(self) -> None:
        for server in self._servers:
            server.shutdown()
            server.server_close()
        for thread in self._threads:
            thread.join(timeout=5)
        self._servers = []
        self._threads = []

    @property
    def host(self) -> str:
        return self.hosts[0]

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def url_for(self, relative: str) -> str:
        return f"{self.base_url}/{relative.lstrip('/')}"

    def file_digest(self, relative: str) -> str:
        return sha256_file(self.root / relative.lstrip("/"))

    def inventory(self) -> dict[str, dict[str, Any]]:
        inventory: dict[str, dict[str, Any]] = {}
        for path in sorted(self.root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(self.root).as_posix()
            inventory[relative] = {
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
                "url": self.url_for(relative),
            }
        return inventory

    def __enter__(self) -> "MediaServer":
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.stop()


def port_holder_pid(port: int) -> int | None:
    """Best-effort lookup of the process listening on a port (no writes)."""

    try:
        import subprocess

        completed = subprocess.run(
            ["ss", "-ltnp", f"sport = :{port}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:  # noqa: BLE001 - diagnostics only
        return None
    for line in completed.stdout.splitlines():
        if "pid=" not in line:
            continue
        for fragment in line.split("pid=")[1:]:
            digits = "".join(character for character in fragment.split(",")[0] if character.isdigit())
            if digits:
                return int(digits)
    return None


def file_is_stable(path: Path, *, wait_seconds: float = 0.5) -> bool:
    if not path.exists():
        return False
    first = path.stat().st_size
    time.sleep(wait_seconds)
    return path.exists() and path.stat().st_size == first


def ensure_writable(directory: Path) -> bool:
    probe = directory / ".s1-write-probe"
    try:
        probe.write_bytes(b"probe")
        os.chmod(probe, 0o600)
        probe.unlink()
    except OSError:
        return False
    return True
