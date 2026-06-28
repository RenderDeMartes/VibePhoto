"""Tests for cross-platform path resolution."""

from __future__ import annotations

from pathlib import Path

from vibephoto.core.paths import AppPaths


def test_under_builds_expected_layout(tmp_path: Path) -> None:
    paths = AppPaths.under(tmp_path)
    assert paths.config_dir == tmp_path / "config"
    assert paths.data_dir == tmp_path / "data"
    assert paths.cache_dir == tmp_path / "cache"
    assert paths.log_dir == tmp_path / "logs"
    assert paths.settings_file == tmp_path / "config" / "settings.json"
    assert paths.catalogs_dir == tmp_path / "data" / "catalogs"


def test_ensure_creates_all_directories(tmp_path: Path) -> None:
    paths = AppPaths.under(tmp_path)
    paths.ensure()
    for d in (paths.config_dir, paths.data_dir, paths.cache_dir, paths.log_dir,
              paths.catalogs_dir, paths.previews_dir, paths.thumbnails_dir):
        assert d.is_dir()


def test_platform_default_is_constructable() -> None:
    paths = AppPaths.platform_default()
    assert isinstance(paths.config_dir, Path)
    assert paths.config_dir.name  # non-empty
