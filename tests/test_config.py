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


# --- PlaybackInfo field configuration -------------------------------------

def _write_config(tmp_path: Path, lines: list[str]) -> Path:
    config_file = tmp_path / "JellyfinProxy.toml"
    config_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return config_file


def test_from_env_has_empty_playback_info_field_tables(monkeypatch) -> None:
    monkeypatch.delenv("PLAYBACK_INFO_RESPONSE_FIELDS", raising=False)
    monkeypatch.delenv("PLAYBACK_INFO_MEDIA_SOURCE_FIELDS", raising=False)

    settings = Settings.from_env()

    assert settings.playback_info_response_fields == {}
    assert settings.playback_info_media_source_fields == {}


def test_from_file_without_playback_info_table_keeps_empty_fields(tmp_path: Path) -> None:
    config_file = _write_config(tmp_path, ['listen_port = 8097'])
    settings = Settings.from_file(config_file)
    assert settings.playback_info_response_fields == {}
    assert settings.playback_info_media_source_fields == {}


def test_from_file_with_empty_playback_info_table_keeps_empty_fields(tmp_path: Path) -> None:
    config_file = _write_config(tmp_path, ["[playback_info]"])
    settings = Settings.from_file(config_file)
    assert settings.playback_info_response_fields == {}
    assert settings.playback_info_media_source_fields == {}


def test_from_file_with_explicit_empty_field_tables_keeps_empty_fields(tmp_path: Path) -> None:
    config_file = _write_config(tmp_path, [
        "[playback_info.response_fields]",
        "[playback_info.media_source_fields]",
    ])
    settings = Settings.from_file(config_file)
    assert settings.playback_info_response_fields == {}
    assert settings.playback_info_media_source_fields == {}


def test_from_file_reads_only_listed_fields_and_keeps_root_settings(tmp_path: Path) -> None:
    config_file = _write_config(tmp_path, [
        'jellyfin_url = "http://jellyfin:8096"',
        'listen_port = 8097',
        "[playback_info.response_fields]",
        'ServerName = "Home"',
        "[playback_info.media_source_fields]",
        'SupportsDirectPlay = true',
        "[playback_info.media_source_fields.Nested]",
        'Kept = "as-object"',
    ])

    settings = Settings.from_file(config_file)

    assert settings.playback_info_response_fields == {"ServerName": "Home"}
    assert settings.playback_info_media_source_fields == {
        "SupportsDirectPlay": True,
        "Nested": {"Kept": "as-object"},
    }
    # The tables sit after the root keys here, so the root settings still load.
    assert settings.jellyfin_url == "http://jellyfin:8096"
    assert settings.listen_port == 8097


def test_from_file_keeps_json_value_types(tmp_path: Path) -> None:
    config_file = _write_config(tmp_path, [
        "[playback_info.response_fields]",
        'Text = "false"',
        "Flag = false",
        "Whole = 7",
        "Fraction = 1.5",
        "Items = [1, \"two\", false]",
        'Mapping = { inner = [{ deep = 1 }] }',
        "[playback_info.media_source_fields]",
        'Protocol = "File"',
        "SupportsTranscoding = false",
    ])

    settings = Settings.from_file(config_file)

    response_fields = settings.playback_info_response_fields
    assert response_fields["Text"] == "false"
    assert response_fields["Text"] is not False
    assert response_fields["Flag"] is False
    assert response_fields["Whole"] == 7
    assert isinstance(response_fields["Whole"], int)
    assert response_fields["Fraction"] == 1.5
    assert response_fields["Items"] == [1, "two", False]
    assert response_fields["Mapping"] == {"inner": [{"deep": 1}]}
    assert settings.playback_info_media_source_fields == {
        "Protocol": "File",
        "SupportsTranscoding": False,
    }


def test_from_file_field_tables_are_independent_copies(tmp_path: Path) -> None:
    config_file = _write_config(tmp_path, [
        "[playback_info.media_source_fields]",
        "Tags = [\"a\"]",
    ])

    first = Settings.from_file(config_file)
    second = Settings.from_file(config_file)
    first.playback_info_media_source_fields["Tags"].append("mutated")

    assert first.playback_info_media_source_fields["Tags"] == ["a", "mutated"]
    assert second.playback_info_media_source_fields["Tags"] == ["a"]


def test_from_env_has_no_playback_info_field_environment_variables(monkeypatch) -> None:
    """Only TOML configures field overrides; no environment variable is invented."""

    monkeypatch.setenv("PLAYBACK_INFO_RESPONSE_FIELDS", '{"ServerName":"Env"}')
    monkeypatch.setenv("PLAYBACK_INFO_MEDIA_SOURCE_FIELDS", '{"Protocol":"File"}')

    settings = Settings.from_env()

    assert settings.playback_info_response_fields == {}
    assert settings.playback_info_media_source_fields == {}


@pytest.mark.parametrize(("lines", "location"), [
    pytest.param(["playback_info = 7"], "playback_info", id="non-table-playback-info"),
    pytest.param(['playback_info = "text"'], "playback_info", id="string-playback-info"),
    pytest.param(
        ["[playback_info]", 'response_fields = "ServerName"'],
        "playback_info.response_fields",
        id="non-table-response-fields",
    ),
    pytest.param(
        ["[playback_info]", 'media_source_fields = ["Protocol"]'],
        "playback_info.media_source_fields",
        id="array-media-source-fields",
    ),
    pytest.param(
        ["[playback_info.response_fields]", '"" = "value"'],
        "playback_info.response_fields",
        id="empty-response-field-name",
    ),
    pytest.param(
        ["[playback_info.media_source_fields]", '"" = "value"'],
        "playback_info.media_source_fields",
        id="empty-media-source-field-name",
    ),
    pytest.param(
        ["[playback_info.response_fields]", 'MediaSources = []'],
        "playback_info.response_fields.MediaSources",
        id="reserved-media-sources",
    ),
    pytest.param(
        ["[playback_info.response_fields]", "Date = 2026-10-25"],
        "playback_info.response_fields.Date",
        id="date-value",
    ),
    pytest.param(
        ["[playback_info.media_source_fields]", "Time = 07:30:00"],
        "playback_info.media_source_fields.Time",
        id="time-value",
    ),
    pytest.param(
        ["[playback_info.media_source_fields]", "At = 2026-10-25T07:30:00Z"],
        "playback_info.media_source_fields.At",
        id="datetime-value",
    ),
    pytest.param(
        ["[playback_info.response_fields]", "Number = nan"],
        "playback_info.response_fields.Number",
        id="nan-value",
    ),
    pytest.param(
        ["[playback_info.response_fields]", "Number = -inf"],
        "playback_info.response_fields.Number",
        id="inf-value",
    ),
    pytest.param(
        ["[playback_info.response_fields]", 'Nested = { inner = nan }'],
        "playback_info.response_fields.Nested.inner",
        id="nested-nan-value",
    ),
    pytest.param(
        ["[playback_info.media_source_fields]", "Items = [1, { deep = { when = 07:30:00 } }]"],
        "playback_info.media_source_fields.Items[1].deep.when",
        id="deep-time-value",
    ),
])
def test_from_file_rejects_invalid_field_configuration(
    tmp_path: Path, lines: list[str], location: str,
) -> None:
    config_file = _write_config(tmp_path, lines)

    with pytest.raises(ValueError) as excinfo:
        Settings.from_file(config_file)

    message = str(excinfo.value)
    assert location in message
    # The message names the location and the offending type only.
    assert "Traceback" not in message
    assert "nan" not in message.replace("NaN", "").lower()
    assert "07:30:00" not in message
    assert "2026-10-25" not in message


def test_invalid_field_configuration_error_does_not_leak_config_value(tmp_path: Path) -> None:
    secret = "super-secret-media-host"
    config_file = _write_config(tmp_path, [
        "[playback_info.response_fields]",
        "At = 2026-10-25T07:30:00Z",
        f'Note = "{secret}"',
    ])

    with pytest.raises(ValueError) as excinfo:
        Settings.from_file(config_file)

    assert secret not in str(excinfo.value)
    assert "playback_info.response_fields.At" in str(excinfo.value)
    assert "datetime" in str(excinfo.value)


def test_startup_reports_invalid_field_configuration_without_value(tmp_path: Path) -> None:
    secret = "super-secret-media-host"
    config_file = _write_config(tmp_path, [
        f'log_file = "{tmp_path / "app.log"}"',
        f'access_log_file = "{tmp_path / "access.log"}"',
        "[playback_info.response_fields]",
        f'Note = "{secret}"',
        "At = 2026-10-25",
    ])
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("PLAYBACK_INFO_")
    }

    completed = subprocess.run(
        [sys.executable, "main.py", "--config", str(config_file)],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )

    assert completed.returncode != 0
    assert "playback_info.response_fields.At" in completed.stderr
    assert secret not in completed.stderr
    assert secret not in completed.stdout
