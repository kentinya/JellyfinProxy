from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from config import Settings

REPO_ROOT = Path(__file__).resolve().parents[1]
REMOVED_SETTINGS = (
    "playback_cache_bypass_clients",
    "playback_info_cache_enabled",
    "playback_info_cache_ttl_seconds",
    "playback_info_cache_max_entries",
)
REMOVED_ENVIRONMENT = {
    "PLAYBACK_CACHE_BYPASS_CLIENTS": "LegacyCacheOnly",
    "PLAYBACK_INFO_CACHE_ENABLED": "maybe-not-a-bool",
    "PLAYBACK_INFO_CACHE_TTL_SECONDS": "not-a-number",
    "PLAYBACK_INFO_CACHE_MAX_ENTRIES": "also-not-a-number",
}
LEGACY_TOML_LINES = [
    'playback_cache_bypass_clients = ["LegacyCacheOnly"]',
    'playback_info_cache_enabled = "maybe-not-a-bool"',
    'playback_info_cache_ttl_seconds = "not-a-number"',
    'playback_info_cache_max_entries = "also-not-a-number"',
]


def _clear_legacy_environment(monkeypatch) -> None:
    for name in REMOVED_ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)


def test_settings_load_from_toml_and_resolve_relative_log_path(tmp_path: Path) -> None:
    config_file = tmp_path / "JellyfinProxy.toml"
    config_file.write_text(
        '\n'.join([
            'jellyfin_url = "http://jellyfin:8096/"',
            'listen_host = "127.0.0.1"',
            'listen_port = 9000',
            'bypass_clients = ["Infuse"]',
            'playback_bypass_clients = ["PlaybackOnlyBypass"]',
            'video_bypass_clients = ["VideoOnlyBypass"]',
            'debug = true',
            'request_timeout_seconds = 12.5',
            'log_level = "DEBUG"',
            'log_file = "logs/JellyfinProxy.log"',
        ]),
        encoding="utf-8",
    )

    settings = Settings.from_file(config_file)
    assert settings.jellyfin_url == "http://jellyfin:8096"
    assert settings.listen_host == "127.0.0.1"
    assert settings.listen_port == 9000
    assert settings.bypass_clients == ("Infuse",)
    assert settings.playback_bypass_clients == ("PlaybackOnlyBypass",)
    assert settings.video_bypass_clients == ("VideoOnlyBypass",)
    assert settings.debug is True
    assert settings.request_timeout_seconds == 12.5
    assert settings.log_level == "DEBUG"
    assert settings.log_file == str(tmp_path / "logs/JellyfinProxy.log")
    assert settings.access_log_file == str(tmp_path / "access.log")


def test_missing_config_has_clear_error(tmp_path: Path) -> None:
    try:
        Settings.from_file(tmp_path / "missing.toml")
    except ValueError as exc:
        assert "Configuration file not found" in str(exc)
    else:
        raise AssertionError("missing configuration should fail")


def test_empty_log_file_disables_file_logging(tmp_path: Path, monkeypatch) -> None:
    config_file = tmp_path / "JellyfinProxy.toml"
    config_file.write_text('log_file = "JellyfinProxy.log"', encoding="utf-8")
    monkeypatch.setenv("LOG_FILE", "")
    assert Settings.from_file(config_file).log_file == ""


def test_from_file_ignores_legacy_cache_keys(tmp_path: Path, monkeypatch) -> None:
    _clear_legacy_environment(monkeypatch)
    config_file = tmp_path / "JellyfinProxy.toml"
    config_file.write_text(
        '\n'.join([
            'jellyfin_url = "http://jellyfin:8096"',
            'bypass_clients = ["Infuse"]',
            *LEGACY_TOML_LINES,
        ]),
        encoding="utf-8",
    )

    settings = Settings.from_file(config_file)

    for name in REMOVED_SETTINGS:
        assert not hasattr(settings, name), name
    # A legacy single client list must not leak into the kept bypass tables.
    assert settings.bypass_clients == ("Infuse",)
    assert settings.playback_bypass_clients == ()
    assert settings.video_bypass_clients == ()
    assert settings.jellyfin_url == "http://jellyfin:8096"


def test_from_env_ignores_legacy_cache_variables(monkeypatch) -> None:
    for name, value in REMOVED_ENVIRONMENT.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("BYPASS_CLIENTS", "Infuse")

    settings = Settings.from_env()

    for name in REMOVED_SETTINGS:
        assert not hasattr(settings, name), name
    assert settings.bypass_clients == ("Infuse",)
    assert settings.playback_bypass_clients == ()
    assert settings.video_bypass_clients == ()


def test_from_file_ignores_legacy_cache_environment_variables(
    tmp_path: Path, monkeypatch
) -> None:
    for name, value in REMOVED_ENVIRONMENT.items():
        monkeypatch.setenv(name, value)
    config_file = tmp_path / "JellyfinProxy.toml"
    config_file.write_text('log_level = "DEBUG"', encoding="utf-8")

    settings = Settings.from_file(config_file)

    for name in REMOVED_SETTINGS:
        assert not hasattr(settings, name), name
    assert settings.log_level == "DEBUG"


@pytest.mark.parametrize("key", REMOVED_SETTINGS)
def test_legacy_cache_settings_cannot_be_reintroduced(key: str) -> None:
    with pytest.raises(TypeError):
        replace(Settings.from_env(), **{key: True})
    assert key not in Settings.__dataclass_fields__


def test_module_settings_and_startup_ignore_legacy_cache_environment(
    tmp_path: Path,
) -> None:
    """Importing the config module and the app must not parse the old values."""

    config_file = tmp_path / "JellyfinProxy.toml"
    config_file.write_text(
        '\n'.join([
            f'log_file = "{tmp_path / "app.log"}"',
            f'access_log_file = "{tmp_path / "access.log"}"',
            *LEGACY_TOML_LINES,
        ]),
        encoding="utf-8",
    )
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in REMOVED_ENVIRONMENT
    }
    environment.update(REMOVED_ENVIRONMENT)

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import dataclasses, config, main; "
                "print(sorted(f.name for f in dataclasses.fields(config.settings))); "
                "print(config.settings.jellyfin_url)"
            ),
        ],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Traceback" not in completed.stderr
    assert "ValueError" not in completed.stderr
    for name in REMOVED_SETTINGS:
        assert name not in completed.stdout
    # The startup path still resolves the untouched settings.
    assert "http://127.0.0.1:8096" in completed.stdout
