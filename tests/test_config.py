from __future__ import annotations

from pathlib import Path

from config import Settings


def test_settings_load_from_toml_and_resolve_relative_log_path(tmp_path: Path) -> None:
    config_file = tmp_path / "mediawarp.toml"
    config_file.write_text(
        '\n'.join([
            'jellyfin_url = "http://jellyfin:8096/"',
            'listen_host = "127.0.0.1"',
            'listen_port = 9000',
            'bypass_clients = ["Infuse"]',
            'debug = true',
            'request_timeout_seconds = 12.5',
            'log_level = "DEBUG"',
            'log_file = "logs/mediawarp.log"',
        ]),
        encoding="utf-8",
    )

    settings = Settings.from_file(config_file)
    assert settings.jellyfin_url == "http://jellyfin:8096"
    assert settings.listen_host == "127.0.0.1"
    assert settings.listen_port == 9000
    assert settings.bypass_clients == ("Infuse",)
    assert settings.debug is True
    assert settings.request_timeout_seconds == 12.5
    assert settings.log_level == "DEBUG"
    assert settings.log_file == str(tmp_path / "logs/mediawarp.log")


def test_missing_config_has_clear_error(tmp_path: Path) -> None:
    try:
        Settings.from_file(tmp_path / "missing.toml")
    except ValueError as exc:
        assert "Configuration file not found" in str(exc)
    else:
        raise AssertionError("missing configuration should fail")
