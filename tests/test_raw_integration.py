"""Integration tests for the real rawpy/LibRaw adapter.

Skipped entirely when the ``raw`` extra (rawpy) is not installed. The non-RAW
error-path tests run against LibRaw itself with no sample files needed; the full
end-to-end decode runs only when ``VIBEPHOTO_TEST_RAW`` points at a real RAW file,
so it can be verified against actual camera files without committing large
binaries to the repo.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("rawpy", reason="requires the 'raw' extra (rawpy/LibRaw)")
pytestmark = pytest.mark.integration

from vibephoto.raw.decoder import RawpyDecoder, default_registry  # noqa: E402
from vibephoto.raw.formats import RAW_EXTENSIONS  # noqa: E402
from vibephoto.raw.service import RawService  # noqa: E402

_SAMPLE_RAW = os.environ.get("VIBEPHOTO_TEST_RAW")
#: A tiny synthetic Bayer DNG committed under tests/data (see make_synthetic_dng.py).
#: It has no embedded preview, so it also covers the half-size-render fallback.
_FIXTURE_DNG = Path(__file__).parent / "data" / "synthetic.dng"


def test_default_registry_has_rawpy_when_installed() -> None:
    assert default_registry().available is True


def test_rawpy_decoder_handles_all_target_formats() -> None:
    decoder = RawpyDecoder()
    for ext in RAW_EXTENSIONS:
        assert decoder.handles(ext)
    assert decoder.handles(".CR3") is True  # dot + uppercase tolerated
    assert decoder.handles("jpg") is False


def test_inspect_on_jpeg_degrades_to_none(make_jpeg, tmp_path: Path) -> None:
    # A JPEG is not a RAW; LibRaw rejects it and the adapter returns None.
    jpeg = make_jpeg(tmp_path / "not_raw.jpg")
    decoder = RawpyDecoder()
    assert decoder.inspect(jpeg) is None
    assert decoder.decode(jpeg) is None


def test_inspect_on_garbage_with_raw_extension_degrades_to_none(tmp_path: Path) -> None:
    fake = tmp_path / "corrupt.cr3"
    fake.write_bytes(b"this is not a real raw file" * 8)
    assert RawpyDecoder().inspect(fake) is None
    assert RawpyDecoder().decode(fake) is None


def test_service_read_metadata_on_nonraw_returns_none(make_jpeg, tmp_path: Path) -> None:
    # RawService is asked for a .cr2 but the bytes are a JPEG -> graceful None.
    bad = tmp_path / "mislabeled.cr2"
    bad.write_bytes(make_jpeg(tmp_path / "real.jpg").read_bytes())
    assert RawService().read_metadata(bad) is None


@pytest.mark.skipif(not _FIXTURE_DNG.is_file(), reason="synthetic DNG fixture missing")
def test_synthetic_dng_decodes_through_real_libraw() -> None:
    """The committed synthetic DNG decodes through the real LibRaw adapter,
    covering the happy path (and the no-embedded-preview render fallback) in CI."""
    service = RawService()
    assert service.available is True

    preview = service.load_preview(_FIXTURE_DNG)
    assert preview is not None and preview[:2] == b"\xff\xd8"  # rendered JPEG

    info = service.read_metadata(_FIXTURE_DNG)
    assert info is not None and (info.width, info.height) == (128, 96)

    image = service.decode(_FIXTURE_DNG)
    assert image is not None and image.rgb.shape == (96, 128, 3)
    assert image.rgb.dtype == np.uint16  # real 16-bit demosaic, not the 8-bit JPEG

    # A half-size decode is the fast path the live preview uses.
    half = service.decode(_FIXTURE_DNG, half_size=True)
    assert half is not None and max(half.width, half.height) < 128

    # As-shot colour temperature is computed from the camera calibration (or None).
    temperature = service.as_shot_temperature(_FIXTURE_DNG)
    assert temperature is None or 2000.0 <= temperature <= 50000.0


@pytest.mark.skipif(not _FIXTURE_DNG.is_file(), reason="synthetic DNG fixture missing")
def test_thumbnail_cache_renders_raw_via_service(tmp_path: Path) -> None:
    """A RAW file yields a real thumbnail through ThumbnailCache + RawService —
    the Phase-3 headline: RAW files show previews instead of the grey placeholder."""
    from vibephoto.cache.thumbnails import ThumbnailCache
    from vibephoto.core.config import CacheSettings
    from vibephoto.core.paths import AppPaths

    paths = AppPaths.under(tmp_path).ensure()
    with_raw = ThumbnailCache(paths, CacheSettings(), RawService())
    thumb = with_raw.get_or_create(_FIXTURE_DNG, key="dng:fixture", size=256)
    assert thumb is not None and thumb.exists() and thumb.stat().st_size > 0

    # Without RAW support the same file has no thumbnail (grid falls back to placeholder).
    without_raw = ThumbnailCache(AppPaths.under(tmp_path / "b").ensure(), CacheSettings(), None)
    assert without_raw.get_or_create(_FIXTURE_DNG, key="dng:fixture2") is None


@pytest.mark.skipif(
    not _SAMPLE_RAW, reason="set VIBEPHOTO_TEST_RAW=<path to a real RAW file> to run"
)
def test_real_raw_file_end_to_end() -> None:
    path = Path(_SAMPLE_RAW or "")
    assert path.is_file(), f"VIBEPHOTO_TEST_RAW does not exist: {path}"
    service = RawService()

    preview = service.load_preview(path)
    assert preview is not None and preview[:2] == b"\xff\xd8"  # JPEG SOI marker

    info = service.read_metadata(path)
    assert info is not None
    assert info.width and info.height and info.width > 0 and info.height > 0

    image = service.decode(path)
    assert image is not None
    assert image.rgb.ndim == 3 and image.rgb.shape[2] == 3
    assert image.width > 0 and image.height > 0
