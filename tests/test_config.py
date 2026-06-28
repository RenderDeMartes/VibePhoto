"""Tests for the layered configuration system."""

from __future__ import annotations

import json

import pytest

from vibephoto.core.config import (
    AppSettings,
    load_settings,
    save_settings,
)
from vibephoto.core.errors import ConfigError
from vibephoto.core.paths import AppPaths


def test_defaults_are_sensible(default_settings: AppSettings) -> None:
    assert default_settings.general.theme == "dark"
    assert default_settings.logging.level == "INFO"
    assert default_settings.metadata.sidecar_mode == "hybrid"
    assert default_settings.cache.preview_quality == 85


def test_load_with_no_file_returns_defaults(app_paths: AppPaths) -> None:
    settings = load_settings(app_paths, environ={})
    assert settings == AppSettings()


def test_file_overrides_defaults(app_paths: AppPaths) -> None:
    app_paths.settings_file.write_text(
        json.dumps({"general": {"theme": "light"}, "cache": {"preview_quality": 70}}),
        encoding="utf-8",
    )
    settings = load_settings(app_paths, environ={})
    assert settings.general.theme == "light"
    assert settings.cache.preview_quality == 70
    # Untouched sections keep defaults.
    assert settings.logging.level == "INFO"


def test_env_overrides_file(app_paths: AppPaths) -> None:
    app_paths.settings_file.write_text(
        json.dumps({"logging": {"level": "WARNING"}}), encoding="utf-8"
    )
    env = {"VIBEPHOTO_LOGGING__LEVEL": "DEBUG", "VIBEPHOTO_PROCESSING__USE_GPU": "true"}
    settings = load_settings(app_paths, environ=env)
    assert settings.logging.level == "DEBUG"
    assert settings.processing.use_gpu is True


def test_bool_coercion_from_env(app_paths: AppPaths) -> None:
    settings = load_settings(app_paths, environ={"VIBEPHOTO_GENERAL__TELEMETRY_ENABLED": "no"})
    assert settings.general.telemetry_enabled is False


def test_int_coercion_from_env(app_paths: AppPaths) -> None:
    settings = load_settings(app_paths, environ={"VIBEPHOTO_CACHE__PREVIEW_QUALITY": "60"})
    assert settings.cache.preview_quality == 60


def test_invalid_theme_raises(app_paths: AppPaths) -> None:
    app_paths.settings_file.write_text(
        json.dumps({"general": {"theme": "neon"}}), encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="Invalid theme"):
        load_settings(app_paths, environ={})


def test_invalid_preview_quality_raises(app_paths: AppPaths) -> None:
    app_paths.settings_file.write_text(
        json.dumps({"cache": {"preview_quality": 250}}), encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="preview_quality"):
        load_settings(app_paths, environ={})


def test_malformed_json_raises(app_paths: AppPaths) -> None:
    app_paths.settings_file.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ConfigError, match="Failed to read settings"):
        load_settings(app_paths, environ={})


def test_unknown_keys_are_ignored(app_paths: AppPaths) -> None:
    # Forward-compat: a newer file with extra keys still loads.
    app_paths.settings_file.write_text(
        json.dumps({"general": {"theme": "dark", "future_flag": True}}), encoding="utf-8"
    )
    settings = load_settings(app_paths, environ={})
    assert settings.general.theme == "dark"


def test_save_then_load_roundtrip(app_paths: AppPaths) -> None:
    original = AppSettings()
    original.general.theme = "light"
    original.processing.worker_threads = 8
    path = save_settings(original, app_paths)
    assert path.is_file()
    reloaded = load_settings(app_paths, environ={})
    assert reloaded.general.theme == "light"
    assert reloaded.processing.worker_threads == 8


def test_save_is_atomic_no_tmp_left(app_paths: AppPaths) -> None:
    save_settings(AppSettings(), app_paths)
    leftovers = list(app_paths.config_dir.glob("*.tmp"))
    assert leftovers == []


def test_resolved_worker_threads_expands_auto() -> None:
    settings = AppSettings()
    assert settings.processing.worker_threads == 0
    assert settings.processing.resolved_worker_threads >= 1
