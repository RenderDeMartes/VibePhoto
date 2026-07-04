"""Tests for the smart-preview cache (decoded RAW base buffers)."""

from __future__ import annotations

import numpy as np

from vibephoto.cache.previews import PreviewCache
from vibephoto.core.config import CacheSettings
from vibephoto.core.paths import AppPaths
from vibephoto.processing.image_buffer import ImageBuffer


def _buffer(seed: int = 3) -> ImageBuffer:
    rng = np.random.default_rng(seed)
    return ImageBuffer(rng.random((20, 30, 3), dtype=np.float32), "linear")


def test_roundtrip_preserves_buffer_and_as_shot(tmp_path) -> None:
    cache = PreviewCache(AppPaths.under(tmp_path).ensure(), CacheSettings())
    assert cache.load("abc") is None
    assert not cache.contains("abc")

    original = _buffer()
    cache.save("abc", original, 5200.0)
    assert cache.contains("abc")
    loaded = cache.load("abc")
    assert loaded is not None
    buffer, as_shot = loaded
    assert as_shot == 5200.0
    assert buffer.colorspace == "linear"
    # float16 storage: identical shape, tiny quantisation only.
    assert buffer.data.shape == original.data.shape
    assert np.allclose(buffer.data, original.data, atol=2e-3)


def test_missing_as_shot_roundtrips_as_none(tmp_path) -> None:
    cache = PreviewCache(AppPaths.under(tmp_path).ensure(), CacheSettings())
    cache.save("xyz", _buffer(), None)
    loaded = cache.load("xyz")
    assert loaded is not None
    assert loaded[1] is None


def test_persists_across_instances(tmp_path) -> None:
    paths = AppPaths.under(tmp_path).ensure()
    PreviewCache(paths, CacheSettings()).save("k1", _buffer(), 4800.0)
    reopened = PreviewCache(paths, CacheSettings())  # cold RAM — must hit disk
    assert reopened.contains("k1")
    loaded = reopened.load("k1")
    assert loaded is not None and loaded[1] == 4800.0


def test_zero_budget_evicts_disk_entries(tmp_path) -> None:
    paths = AppPaths.under(tmp_path).ensure()
    cache = PreviewCache(paths, CacheSettings(max_preview_cache_mb=0))
    cache.save("gone", _buffer(), None)
    # The RAM LRU may still hold it, but a fresh instance sees an empty disk.
    assert not PreviewCache(paths, CacheSettings()).contains("gone")
