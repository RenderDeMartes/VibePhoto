"""Tests for the thumbnail cache."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from vibephoto.cache.thumbnails import ThumbnailCache
from vibephoto.core.config import CacheSettings
from vibephoto.core.paths import AppPaths


def _cache(tmp_path: Path) -> ThumbnailCache:
    paths = AppPaths.under(tmp_path).ensure()
    return ThumbnailCache(paths, CacheSettings())


def test_generates_thumbnail(make_jpeg, tmp_path: Path) -> None:
    src = make_jpeg(tmp_path / "src" / "a.jpg", size=(1600, 1200))
    cache = _cache(tmp_path)
    thumb = cache.get_or_create(src, key="1:abc", size=256)
    assert thumb is not None and thumb.exists()
    with Image.open(thumb) as img:
        assert max(img.size) <= 256


def test_thumbnail_is_cached_not_regenerated(make_jpeg, tmp_path: Path) -> None:
    src = make_jpeg(tmp_path / "src" / "a.jpg")
    cache = _cache(tmp_path)
    first = cache.get_or_create(src, key="1:abc", size=128)
    mtime = first.stat().st_mtime_ns
    second = cache.get_or_create(src, key="1:abc", size=128)
    assert second == first
    assert second.stat().st_mtime_ns == mtime  # not rewritten


def test_get_bytes_uses_memory_lru(make_jpeg, tmp_path: Path) -> None:
    src = make_jpeg(tmp_path / "src" / "a.jpg")
    cache = _cache(tmp_path)
    cache.get_or_create(src, key="1:abc", size=128)
    data = cache.get_bytes("1:abc", size=128)
    assert data is not None and data[:2] == b"\xff\xd8"  # JPEG SOI
    assert cache.memory_bytes > 0


def test_unreadable_source_returns_none(tmp_path: Path) -> None:
    bogus = tmp_path / "bad.jpg"
    bogus.write_bytes(b"nope")
    cache = _cache(tmp_path)
    assert cache.get_or_create(bogus, key="1:bad") is None
