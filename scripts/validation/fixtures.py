"""Deterministic fixtures for the real Jellyfin 12.3 baseline.

Creates the isolated library, users and media corpus inside the run directory.
Only test infrastructure may touch files here; the proxy under test never does.
"""

from __future__ import annotations

import json
import os
import random
import re
import secrets
import string
import time
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable, Mapping

import httpx

from scripts.validation.common import (
    ValidationError,
    ensure_directory,
    sha256_file,
    utc_now,
    wait_for,
    write_json,
    write_private,
    write_text,
)
from scripts.validation.environment import JellyfinContainer, RunPaths

ADMIN_NAME = "s1admin"
USER_NAMES = ("s1user1", "s1user2")
DEVICE_IDS = ("s1-device-alpha", "s1-device-beta")

#: Fixed client identities used by the bypass matrix (must match proxy config).
BYPASS_CLIENTS = {
    "normal": "PlainClient",
    "playback": "PlaybackOnly",
    "video": "VideoOnly",
    "global": "GlobalClient",
    "cache": "CacheOnly",
    "overlap": "OverlapClient",
}

LIBRARY_NAME = "S1Validation"
IMAGE_NAME = "poster.jpg"


def _password() -> str:
    alphabet = string.ascii_letters + string.digits
    return "S1-" + "".join(secrets.choice(alphabet) for _ in range(20))


@dataclass
class Credentials:
    admin_name: str
    admin_password: str
    admin_token: str
    users: dict[str, dict[str, str]]

    def public_view(self) -> dict[str, Any]:
        return {
            "admin_name": self.admin_name,
            "admin_token_sha256_prefix": sha256(self.admin_token.encode()).hexdigest()[:12],
            "users": {
                name: {
                    "user_id": entry["user_id"],
                    "token_sha256_prefix": sha256(entry["token"].encode()).hexdigest()[:12],
                }
                for name, entry in self.users.items()
            },
        }


class JellyfinApi:
    """Minimal Jellyfin REST client used by the validation tool."""

    def __init__(self, base_url: str, token: str | None = None, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._client = httpx.Client(timeout=timeout, follow_redirects=False)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "JellyfinApi":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def headers(self, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        headers = {
            "Authorization": (
                f'MediaBrowser Client="S1Validation", Device="validator", '
                f'DeviceId="s1-validator", Version="1.0"'
                + (f", Token={self.token}" if self.token else "")
            )
        }
        if extra:
            headers.update(extra)
        return headers

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any | None = None,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        content: bytes | None = None,
        retries: int = 3,
    ) -> httpx.Response:
        # A freshly started container can reset connections for a few seconds
        # after the port opens; retry transport errors only.
        last_error: Exception | None = None
        for attempt in range(retries):
            try:
                return self._client.request(
                    method,
                    f"{self.base_url}{path}",
                    headers=self.headers(headers),
                    json=json_body,
                    params=params,
                    content=content,
                )
            except httpx.TransportError as exc:
                last_error = exc
                time.sleep(1 + attempt)
        raise ValidationError(f"{method} {path} failed after {retries} attempts: {last_error}")

    def get_json(self, path: str, **kwargs: Any) -> Any:
        response = self.request("GET", path, **kwargs)
        if response.status_code >= 400:
            raise ValidationError(f"GET {path} failed with {response.status_code}")
        return response.json()

    def authenticate(self, username: str, password: str, *, device_id: str) -> dict[str, Any]:
        response = self._client.post(
            f"{self.base_url}/Users/AuthenticateByName",
            headers={
                "Authorization": (
                    f'MediaBrowser Client="S1Validation", Device="{device_id}", '
                    f'DeviceId="{device_id}", Version="1.0"'
                ),
                "Content-Type": "application/json",
            },
            content=json.dumps({"Username": username, "Pw": password}).encode(),
        )
        if response.status_code != 200:
            raise ValidationError(f"authentication for {username} failed with {response.status_code}")
        return response.json()


# ---------------------------------------------------------------------------
# media corpus
# ---------------------------------------------------------------------------


MEDIA_LAYOUT: tuple[dict[str, Any], ...] = (
    {
        "key": "local",
        "folder": "Local/Local Sample (2020)",
        "file": "Local Sample (2020).mp4",
        "kind": "local",
        "description": "local playable sample with a local poster image",
    },
    {
        "key": "remote",
        "folder": "Remote/Remote Sample (2020)",
        "file": "Remote Sample (2020).strm",
        "kind": "strm",
        "target": "remote-a.mp4",
        "description": "STRM pointing at the controlled HTTP media origin",
    },
    {
        "key": "remote_two",
        "folder": "RemoteTwo/Remote Two (2020)",
        "file": "Remote Two (2020).strm",
        "kind": "strm",
        "target": "remote-b.mp4",
        "description": "second independent remote media source",
    },
    {
        "key": "multi",
        "folder": "Multi/Multi Version (2020)",
        "file": "Multi Version (2020) - 480p.mp4",
        "kind": "local",
        "extra_local": "Multi Version (2020) - 720p.mp4",
        "description": "one item with two local media versions",
    },
    {
        "key": "dynamic",
        "folder": "Dynamic/Dynamic Sample (2020)",
        "file": "Dynamic Sample (2020).strm",
        "kind": "strm",
        "target": "remote-a.mp4",
        "description": "STRM toggled between remote and invalid local path (same item id)",
    },
    {
        "key": "throttle",
        "folder": "Stream/Throttled Sample (2020)",
        "file": "Throttled Sample (2020).strm",
        "kind": "strm",
        "target": "remote-a.mp4?throttle=64000",
        "description": "STRM whose origin throttles so stream cancellation is observable",
    },
)

WEBROOT_ASSETS = ("remote-a.mp4", "remote-b.mp4")
POSTER_SIZE = (320, 180)


def _ffmpeg_args(container: JellyfinContainer, *args: str) -> list[str]:
    return [
        "docker",
        "exec",
        container.name,
        "/usr/lib/jellyfin-ffmpeg/ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        *args,
    ]


def _run_ffmpeg(container: JellyfinContainer, args: Iterable[str]) -> None:
    import subprocess

    completed = subprocess.run(list(args), capture_output=True, text=True, timeout=600)
    if completed.returncode != 0:
        raise ValidationError(
            f"ffmpeg failed ({completed.returncode}): {completed.stderr.strip()[:400]}"
        )


#: Container-side directory holding the controlled origin's source media. It is
#: deliberately outside ``/media/movies`` so the library scanner never indexes it.
ORIGIN_DIR = "/media/.origin"


def generate_media(paths: RunPaths, container: JellyfinContainer) -> dict[str, Any]:
    """Generate tiny deterministic media with the pinned image's own ffmpeg."""

    ensure_directory(paths.media / "movies", 0o755)
    ensure_directory(paths.webroot, 0o755)
    ffmpeg_version = _tool_version(container)
    _run_ffmpeg(container, ["docker", "exec", container.name, "mkdir", "-p", ORIGIN_DIR])
    _run_ffmpeg(
        container,
        _ffmpeg_args(
            container,
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=160x120:rate=10",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=44100",
            "-t",
            "5",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            f"{ORIGIN_DIR}/remote-a.mp4",
        ),
    )
    _run_ffmpeg(
        container,
        _ffmpeg_args(
            container,
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=128x96:rate=10",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:sample_rate=44100",
            "-t",
            "5",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            f"{ORIGIN_DIR}/remote-b.mp4",
        ),
    )
    _populate_local_media(container, paths)
    import subprocess

    for name in WEBROOT_ASSETS:
        completed = subprocess.run(
            ["docker", "cp", f"{container.name}:{ORIGIN_DIR}/{name}", str(paths.webroot / name)],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if completed.returncode != 0:
            raise ValidationError(f"copying {name} out of the container failed: {completed.stderr.strip()[:300]}")
        os.chmod(paths.webroot / name, 0o644)
    write_text(
        paths.private / "ffmpeg.txt",
        f"ffmpeg={ffmpeg_version}\ncommand_variant=docker exec {container.name}\n",
        mode=0o600,
    )
    return {
        "ffmpeg_version": ffmpeg_version,
        "webroot": webroot_name(paths),
        "webroot_sha256": {name: sha256_file(paths.webroot / name) for name in WEBROOT_ASSETS},
        "generated_at": utc_now(),
    }


def webroot_name(paths: RunPaths) -> str:
    return paths.webroot.name


def _tool_version(container: JellyfinContainer) -> str:
    import subprocess

    completed = subprocess.run(
        ["docker", "exec", container.name, "/usr/lib/jellyfin-ffmpeg/ffmpeg", "-version"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    first = (completed.stdout or completed.stderr).splitlines()[0] if completed.returncode == 0 else "unknown"
    return first.strip()


def container_path(paths: RunPaths, host_path: Path) -> str:
    """Translate a run-directory media path into the container's /media view."""

    relative = host_path.resolve().relative_to((paths.media / "movies").resolve())
    return f"/media/movies/{relative.as_posix()}"


def _populate_local_media(container: JellyfinContainer, paths: RunPaths) -> None:
    for entry in MEDIA_LAYOUT:
        folder = ensure_directory(paths.media / "movies" / entry["folder"], 0o755)
        if entry["kind"] == "local":
            target = folder / entry["file"]
            _run_ffmpeg(
                container,
                _ffmpeg_args(
                    container,
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc=size=160x120:rate=10",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=520:sample_rate=44100",
                    "-t",
                    "6",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "ultrafast",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-shortest",
                    container_path(paths, target),
                ),
            )
            if entry.get("extra_local"):
                extra = folder / entry["extra_local"]
                _run_ffmpeg(
                    container,
                    _ffmpeg_args(
                        container,
                        "-f",
                        "lavfi",
                        "-i",
                        "testsrc=size=256x144:rate=10",
                        "-f",
                        "lavfi",
                        "-i",
                        "sine=frequency=300:sample_rate=44100",
                        "-t",
                        "7",
                        "-c:v",
                        "libx264",
                        "-preset",
                        "ultrafast",
                        "-pix_fmt",
                        "yuv420p",
                        "-c:a",
                        "aac",
                        "-shortest",
                        container_path(paths, extra),
                    ),
                )
            _run_ffmpeg(
                container,
                _ffmpeg_args(
                    container,
                    "-f",
                    "lavfi",
                    "-i",
                    f"testsrc=size={POSTER_SIZE[0]}x{POSTER_SIZE[1]}:rate=1",
                    "-frames:v",
                    "1",
                    "-q:v",
                    "5",
                    container_path(paths, folder / IMAGE_NAME),
                ),
            )
    write_json(
        paths.private / "media-layout.json",
        {
            "generated_at": utc_now(),
            "entries": [
                {
                    "key": entry["key"],
                    "folder": entry["folder"],
                    "file": entry["file"],
                    "kind": entry["kind"],
                    "target": entry.get("target"),
                    "extra_local": entry.get("extra_local"),
                    "description": entry["description"],
                }
                for entry in MEDIA_LAYOUT
            ],
        },
        mode=0o600,
    )


def write_strm(paths: RunPaths, entry_key: str, value: str) -> Path:
    entry = next(item for item in MEDIA_LAYOUT if item["key"] == entry_key)
    target = paths.media / "movies" / entry["folder"] / entry["file"]
    ensure_directory(target.parent, 0o755)
    write_text(target, value + "\n", mode=0o644)
    return target


def remote_url(paths: RunPaths, gateway: str, media_port: int, target: str) -> str:
    return f"http://{gateway}:{media_port}/{target.lstrip('/')}"


def media_inventory(paths: RunPaths, gateway: str, media_port: int) -> dict[str, Any]:
    inventory: dict[str, Any] = {"movies": {}, "webroot": {}}
    for path in sorted((paths.media / "movies").rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(paths.media / "movies").as_posix()
        inventory["movies"][relative] = {"size": path.stat().st_size, "sha256": sha256_file(path)}
    for name in WEBROOT_ASSETS:
        path = paths.webroot / name
        inventory["webroot"][name] = {
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
            "url": remote_url(paths, gateway, media_port, name),
        }
    return inventory


# ---------------------------------------------------------------------------
# server bootstrap
# ---------------------------------------------------------------------------


def bootstrap_server(
    container: JellyfinContainer,
    paths: RunPaths,
    *,
    gateway: str,
    media_port: int,
    timeout: float = 240,
) -> Credentials:
    """Complete the startup wizard and create the validation users."""

    credentials_path = paths.credentials
    if credentials_path.exists():
        stored = json.loads(credentials_path.read_text(encoding="utf-8"))
        credentials = Credentials(
            admin_name=stored["admin_name"],
            admin_password=stored["admin_password"],
            admin_token=stored["admin_token"],
            users=stored["users"],
        )
        api = JellyfinApi(container.base_url, credentials.admin_token)
        try:
            api.get_json("/System/Info")
        except (ValidationError, httpx.HTTPError):
            pass
        else:
            api.close()
            return credentials
        api.close()
        # Token no longer valid (e.g. fresh volume): fall through to re-bootstrap.

    with JellyfinApi(container.base_url) as api:
        public = _wait_for_startup_endpoint(container)
        if not public.get("StartupWizardCompleted"):
            admin_password = _password()
            # 12.3 only accepts the wizard calls once /Startup/User answers 200,
            # and it requires user -> configuration -> complete ordering.
            created = api.request("POST", "/Startup/User", json_body={"Name": ADMIN_NAME, "Password": admin_password})
            if created.status_code >= 400:
                raise ValidationError(
                    f"initial admin creation failed with {created.status_code}: {created.text[:200]}"
                )
            configured = api.request(
                "POST",
                "/Startup/Configuration",
                json_body={
                    "ServerName": "S1 Validation",
                    "UICulture": "en-US",
                    "MetadataCountryCode": "US",
                    "PreferredMetadataLanguage": "en",
                },
            )
            if configured.status_code >= 400:
                raise ValidationError(f"startup configuration failed with {configured.status_code}")
            completed = api.request("POST", "/Startup/Complete")
            if completed.status_code >= 400:
                raise ValidationError(f"startup completion failed with {completed.status_code}")
        else:
            admin_password = ""

    admin_token = ""
    admin_password = _resolve_admin_password(container, paths, admin_password)
    authenticated = JellyfinApi(container.base_url).authenticate(ADMIN_NAME, admin_password, device_id="s1-admin")
    admin_token = authenticated["AccessToken"]

    users: dict[str, dict[str, str]] = {}
    with JellyfinApi(container.base_url, admin_token) as api:
        existing = {user["Name"]: user for user in api.get_json("/Users")}
        for index, name in enumerate(USER_NAMES):
            password = _password()
            if name in existing:
                user_id = existing[name]["Id"]
            else:
                created = api.request("POST", "/Users/New", json_body={"Name": name, "Password": password})
                if created.status_code >= 400:
                    raise ValidationError(f"creating user {name} failed with {created.status_code}")
                user_id = created.json()["Id"]
            token = JellyfinApi(container.base_url).authenticate(name, password, device_id=DEVICE_IDS[index])["AccessToken"]
            users[name] = {"user_id": user_id, "password": password, "token": token}

    credentials = Credentials(
        admin_name=ADMIN_NAME,
        admin_password=admin_password,
        admin_token=admin_token,
        users=users,
    )
    write_private(
        credentials_path,
        json.dumps(
            {
                "admin_name": credentials.admin_name,
                "admin_password": credentials.admin_password,
                "admin_token": credentials.admin_token,
                "users": credentials.users,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )
    return credentials


def _resolve_admin_password(container: JellyfinContainer, paths: RunPaths, candidate: str) -> str:
    if candidate:
        return candidate
    if paths.credentials.exists():
        return json.loads(paths.credentials.read_text(encoding="utf-8"))["admin_password"]
    raise ValidationError(
        "startup wizard was already completed but no stored admin credentials exist in this run directory"
    )


def _public_info(container: JellyfinContainer) -> dict[str, Any]:
    with JellyfinApi(container.base_url) as api:
        response = api._client.get(f"{container.base_url}/System/Info/Public")
        return response.json()


def _wait_for_startup_endpoint(container: JellyfinContainer, *, timeout: float = 180) -> dict[str, Any]:
    """Wait until the server serves API responses (not the startup web page)."""

    def _ready() -> dict[str, Any] | None:
        try:
            info = _public_info(container)
        except (httpx.HTTPError, ValueError):
            return None
        probe = "/Users/Public" if info.get("StartupWizardCompleted") else "/Startup/User"
        with JellyfinApi(container.base_url, timeout=10) as api:
            response = api._client.get(f"{container.base_url}{probe}")
        if response.status_code != 200:
            return None
        return info

    return wait_for(_ready, timeout=timeout, interval=2, description="Jellyfin startup API readiness")


def ensure_library(
    container: JellyfinContainer,
    credentials: Credentials,
    paths: RunPaths,
    *,
    gateway: str,
    media_port: int,
) -> dict[str, Any]:
    """Create (or reuse) the isolated movie library and wait for its items."""

    with JellyfinApi(container.base_url, credentials.admin_token) as api:
        folders = api.get_json("/Library/VirtualFolders")
        existing = next((folder for folder in folders if folder.get("Name") == LIBRARY_NAME), None)
        if existing is None:
            response = api.request(
                "POST",
                "/Library/VirtualFolders",
                params={"name": LIBRARY_NAME, "collectionType": "movies", "refreshLibrary": "true"},
                json_body={
                    "LibraryOptions": {
                        "PathInfos": [{"Path": "/media/movies"}],
                        "EnableRealtimeMonitor": False,
                        "EnableInternetProviders": False,
                        "EnablePhotos": True,
                        "EnableLUFSScan": False,
                        "EnableChapterImageExtraction": False,
                        "MetadataCountryCode": "US",
                        "PreferredMetadataLanguage": "en",
                    }
                },
            )
            if response.status_code >= 400:
                raise ValidationError(
                    f"creating library failed with {response.status_code}: {response.text[:200]}"
                )
            existing = None
        items, media_sources = _wait_for_items(api)
        return {"library": LIBRARY_NAME, "existing_before": existing is not None, "item_count": len(items)}


def _wait_for_items(api: JellyfinApi) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    def _probe():
        data = api.get_json(
            "/Items",
            params={
                "Recursive": "true",
                "IncludeItemTypes": "Movie",
                "Fields": "Path,MediaSources,MediaSourceCount",
                "Limit": "200",
            },
        )
        items = data.get("Items") or []
        classes = {entry["key"]: _classify_items(items, entry) for entry in MEDIA_LAYOUT}
        missing = [key for key, found in classes.items() if not found]
        if missing:
            return None
        return items, classes

    return wait_for(_probe, timeout=600, interval=5, description="library items to appear")


def _classify_items(items: list[dict[str, Any]], entry: Mapping[str, Any]) -> list[dict[str, Any]]:
    marker = f"/{entry['folder']}/".casefold()
    return [item for item in items if marker in str(item.get("Path", "")).casefold()]


def refresh_library(container: JellyfinContainer, credentials: Credentials, *, timeout: float = 300) -> None:
    with JellyfinApi(container.base_url, credentials.admin_token, timeout=60) as api:
        response = api.request("POST", "/Library/Refresh")
        if response.status_code >= 400:
            raise ValidationError(f"library refresh failed with {response.status_code}")
    _wait_for_scan(container, credentials, timeout=timeout)


def _wait_for_scan(container: JellyfinContainer, credentials: Credentials, *, timeout: float) -> None:
    def _idle() -> bool | None:
        with JellyfinApi(container.base_url, credentials.admin_token) as api:
            tasks = api.get_json("/ScheduledTasks")
            scans = [
                task
                for task in tasks
                if "Scan Media Library" in str(task.get("Name", ""))
                or str(task.get("Key", "")).endswith("RefreshLibrary")
            ]
            if not scans:
                return None
            if any(task.get("State") == "Running" for task in scans):
                return None
            return True

    wait_for(_idle, timeout=timeout, interval=2, description="library scan to finish")


def item_catalog(container: JellyfinContainer, credentials: Credentials) -> dict[str, dict[str, Any]]:
    """Return the fixed fixture items keyed by their layout key."""

    with JellyfinApi(container.base_url, credentials.admin_token) as api:
        data = api.get_json(
            "/Items",
            params={
                "Recursive": "true",
                "IncludeItemTypes": "Movie",
                "Fields": "Path,MediaSources,MediaSourceCount",
                "Limit": "200",
            },
        )
    items = data.get("Items") or []
    catalog: dict[str, dict[str, Any]] = {}
    for entry in MEDIA_LAYOUT:
        matches = _classify_items(items, entry)
        if not matches:
            raise ValidationError(f"fixture item for {entry['key']} is missing from the library")
        item = matches[0]
        catalog[entry["key"]] = {
            "id": item["Id"],
            "name": item.get("Name"),
            "path": item.get("Path"),
            "media_sources": [
                {
                    "id": source.get("Id"),
                    "protocol": source.get("Protocol"),
                    "path": source.get("Path"),
                    "is_remote": source.get("IsRemote"),
                }
                for source in (item.get("MediaSources") or [])
            ],
        }
    return catalog


def playback_info(container: JellyfinContainer, token: str, item_id: str, *, method: str = "GET") -> httpx.Response:
    with JellyfinApi(container.base_url, token) as api:
        return api.request(method, f"/Items/{item_id}/PlaybackInfo")


def write_fixture_manifest(paths: RunPaths, catalog: Mapping[str, Any], credentials: Credentials) -> None:
    write_json(
        paths.private / "fixtures.json",
        {
            "generated_at": utc_now(),
            "catalog": catalog,
            "credentials": credentials.public_view(),
        },
        mode=0o600,
    )
