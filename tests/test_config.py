from __future__ import annotations

from pathlib import Path

from config import Settings


def test_settings_load_from_toml_and_resolve_relative_log_path(tmp_path: Path) -> None:
    config_file = tmp_path / "JellyfinProxy.toml"
    config_file.write_text(
        '\n'.join([
            'jellyfin_url = "http://jellyfin:8096/"',
            'listen_host = "127.0.0.1"',
            'listen_port = 9000',
            'bypass_clients = ["Infuse"]',
            'playback_bypass_clients = ["PlaybackOnlyBypass"]',
            'playback_cache_bypass_clients = ["NoCacheClient"]',
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
    assert settings.playback_cache_bypass_clients == ("NoCacheClient",)
    assert settings.video_bypass_clients == ("VideoOnlyBypass",)
    assert settings.debug is True
    assert settings.request_timeout_seconds == 12.5
    assert settings.playback_info_cache_enabled is True
    assert settings.playback_info_cache_ttl_seconds == 21600
    assert settings.playback_info_cache_max_entries == 4096
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
