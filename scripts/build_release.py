"""Build and smoke test a native Linux release archive."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import re
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parent.parent
ARCHITECTURES = {"x86_64": "amd64", "aarch64": "arm64"}


def smoke_test(binary: Path, directory: Path, version: str) -> None:
    result = subprocess.check_output([str(binary), "--version"], text=True)
    if result.strip() != f"JellyfinProxy {version}":
        raise RuntimeError(f"Unexpected binary version: {result.strip()}")

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    config = directory / "smoke.toml"
    config.write_text(
        'jellyfin_url = "http://127.0.0.1:1"\n'
        'listen_host = "127.0.0.1"\n'
        f'listen_port = {port}\n'
        'log_file = ""\naccess_log_file = ""\n',
        encoding="utf-8",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with (directory / "smoke.log").open("w+") as log:
        process = subprocess.Popen(
            [str(binary), "--config", str(config)],
            cwd=directory,
            env={
                **os.environ,
                "JELLYFIN_URL": "http://127.0.0.1:1",
                "LISTEN_HOST": "127.0.0.1",
                "LISTEN_PORT": str(port),
                "LOG_FILE": "",
                "ACCESS_LOG_FILE": "",
            },
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline and process.poll() is None:
                try:
                    with opener.open(f"http://127.0.0.1:{port}/openapi.json", timeout=1) as response:
                        document = json.load(response)
                        if document["info"]["version"] != version:
                            raise RuntimeError("OpenAPI version does not match release")
                        if response.headers.get("X-JellyfinProxy-Version") != version:
                            raise RuntimeError("Response version does not match release")
                    print("Frozen binary startup and HTTP smoke: PASS", flush=True)
                    return
                except (urllib.error.URLError, TimeoutError):
                    time.sleep(0.1)
            log.flush()
            log.seek(0)
            raise RuntimeError(f"Frozen binary did not become ready:\n{log.read()}")
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True, help="Release tag matching version.py")
    parser.add_argument("--arch", required=True, choices=("amd64", "arm64"))
    arguments = parser.parse_args()

    match = re.search(r'^__version__ = "([^"]+)"$', (ROOT / "version.py").read_text(), re.MULTILINE)
    if match is None:
        parser.error("Cannot read the release version from version.py")
    version = match.group(1)
    if arguments.tag != f"v{version}":
        parser.error(f"Tag must match version.py: v{version}")
    if sys.platform != "linux" or ARCHITECTURES.get(platform.machine()) != arguments.arch:
        parser.error("PyInstaller requires a native Linux runner matching --arch")

    output = ROOT / "dist" / "release"
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="jellyfinproxy-release-") as temporary:
        directory = Path(temporary)
        subprocess.run(
            [
                sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                "--distpath", str(directory / "bin"),
                "--workpath", str(directory / "work"),
                str(ROOT / "JellyfinProxy.spec"),
            ],
            cwd=ROOT,
            check=True,
        )
        binary = directory / "bin" / "JellyfinProxy"
        smoke_test(binary, directory, version)
        archive = output / f"JellyfinProxy_{arguments.tag}_linux_{arguments.arch}.tar.gz"
        with tarfile.open(archive, "w:gz") as package:
            package.add(binary, arcname="JellyfinProxy")
            package.add(ROOT / "JellyfinProxy.toml", arcname="JellyfinProxy.toml")
        print(f"Release package: {archive}", flush=True)


if __name__ == "__main__":
    main()
