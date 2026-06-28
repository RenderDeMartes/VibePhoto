"""Tests for the export engine: writers and the export service."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from vibephoto.core.paths import AppPaths
from vibephoto.export.presets import BUILTIN_EXPORT_PRESETS, ExportPreset
from vibephoto.export.service import ExportItem, ExportService
from vibephoto.export.writers import apply_watermark, resize_to_long_edge, write_image
from vibephoto.processing.edit_state import EditState
from vibephoto.processing.layers import LayerStack
from vibephoto.processing.loader import ImageLoader
from vibephoto.processing.store import DevelopStore
from vibephoto.raw.service import RawService


def _service(tmp_path: Path) -> tuple[ExportService, DevelopStore]:
    store = DevelopStore(AppPaths.under(tmp_path / "app").ensure())
    return ExportService(ImageLoader(RawService()), store), store


# -- writers -------------------------------------------------------------- #


def test_resize_to_long_edge() -> None:
    arr = np.zeros((100, 200, 3), dtype=np.uint8)
    out = resize_to_long_edge(arr, 100)
    assert max(out.shape[0], out.shape[1]) == 100
    assert resize_to_long_edge(arr, None).shape == arr.shape  # None = unchanged
    assert resize_to_long_edge(arr, 999).shape == arr.shape  # already smaller


def test_watermark_marks_only_when_text_given() -> None:
    arr = np.full((80, 200, 3), 128, dtype=np.uint8)
    assert np.array_equal(apply_watermark(arr, ""), arr)
    assert not np.array_equal(apply_watermark(arr, "© Test"), arr)


def test_write_image_each_format(tmp_path: Path) -> None:
    arr = (np.random.default_rng(0).random((20, 30, 3)) * 255).astype(np.uint8)
    for fmt, ext in (("jpg", "jpg"), ("png", "png"), ("tiff", "tif")):
        dest = tmp_path / f"out.{ext}"
        write_image(arr, dest, fmt, 90)
        assert dest.exists()
        with Image.open(dest) as image:
            assert image.size == (30, 20)


def test_write_16bit_tiff_round_trips_full_precision(tmp_path: Path) -> None:
    # A 16-bit TIFF preserves values that 8-bit would quantise to 256 levels.
    import tifffile

    arr = (np.random.default_rng(2).random((16, 24, 3)) * 65535).astype(np.uint16)
    dest = tmp_path / "deep.tif"
    write_image(arr, dest, "tiff", 100)
    assert dest.exists()
    read = tifffile.imread(str(dest))
    assert read.dtype == np.uint16 and read.shape == (16, 24, 3)
    assert np.array_equal(read, arr)  # lossless 16-bit round trip


def test_write_16bit_rejected_for_non_tiff(tmp_path: Path) -> None:
    arr = np.zeros((4, 4, 3), dtype=np.uint16)
    for fmt in ("jpg", "png"):
        try:
            write_image(arr, tmp_path / f"x.{fmt}", fmt, 90)
        except ValueError:
            continue
        raise AssertionError(f"{fmt} should reject 16-bit input")


def test_watermark_is_depth_agnostic() -> None:
    # The watermark composites in either bit depth, keeping the array's dtype/range.
    for dtype, mid in ((np.uint8, 128), (np.uint16, 30000)):
        arr = np.full((80, 200, 3), mid, dtype=dtype)
        out = apply_watermark(arr, "© Test")
        assert out.dtype == dtype
        assert not np.array_equal(out, arr)
        assert int(out.max()) > mid  # white text brightens some pixels toward max


def test_write_image_embeds_srgb_icc_profile(tmp_path: Path) -> None:
    # Every export declares its colour space (professional RAW editors parity): the written file
    # carries an embedded ICC profile that identifies as sRGB.
    from io import BytesIO

    from PIL import ImageCms

    from vibephoto.export.color_profiles import srgb_icc_bytes

    if srgb_icc_bytes() is None:  # littlecms unavailable in this build
        return
    arr = (np.random.default_rng(1).random((16, 16, 3)) * 255).astype(np.uint8)
    for fmt, ext in (("jpg", "jpg"), ("png", "png"), ("tiff", "tif")):
        dest = tmp_path / f"tagged.{ext}"
        write_image(arr, dest, fmt, 90)
        with Image.open(dest) as image:
            icc = image.info.get("icc_profile")
            assert icc, f"{fmt} export carries no ICC profile"
            description = ImageCms.getProfileDescription(
                ImageCms.ImageCmsProfile(BytesIO(icc))
            )
            assert "srgb" in description.lower()


# -- service -------------------------------------------------------------- #


def test_export_photo_applies_edit_and_resizes(make_jpeg, tmp_path: Path) -> None:
    src = make_jpeg(tmp_path / "a.jpg", size=(800, 600))
    service, store = _service(tmp_path)
    store.save(1, LayerStack.single(EditState(exposure=1.0)))
    preset = ExportPreset("Web", "jpg", 85, 400)

    out = service.export_photo(ExportItem(src, is_raw=False, photo_id=1), preset, tmp_path / "out")

    assert out is not None and out.exists() and out.suffix == ".jpg"
    with Image.open(out) as image:
        assert max(image.size) == 400


def test_export_photo_16bit_tiff_end_to_end(make_jpeg, tmp_path: Path) -> None:
    import tifffile

    src = make_jpeg(tmp_path / "a.jpg", size=(120, 90))
    service, store = _service(tmp_path)
    store.save(1, LayerStack.single(EditState(exposure=0.5)))
    preset = ExportPreset("TIFF16", "tiff", 100, None, bit_depth=16)

    out = service.export_photo(ExportItem(src, is_raw=False, photo_id=1), preset, tmp_path / "out")

    assert out is not None and out.exists() and out.suffix == ".tif"
    read = tifffile.imread(str(out))
    assert read.dtype == np.uint16 and read.shape[2] == 3


def test_export_many_reports_progress(make_jpeg, tmp_path: Path) -> None:
    items = [ExportItem(make_jpeg(tmp_path / f"{i}.jpg"), is_raw=False) for i in range(3)]
    service, _ = _service(tmp_path)
    seen: list[tuple[int, int]] = []

    result = service.export_many(
        items,
        BUILTIN_EXPORT_PRESETS[0],
        tmp_path / "out",
        progress=lambda d, t: seen.append((d, t)),
    )

    assert result.exported == 3 and result.failed == 0
    assert len(result.outputs) == 3
    assert seen[-1] == (3, 3)


def test_export_missing_file_counts_as_failure(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    result = service.export_many(
        [ExportItem(tmp_path / "ghost.jpg", is_raw=False)],
        BUILTIN_EXPORT_PRESETS[0],
        tmp_path / "out",
    )
    assert result.exported == 0 and result.failed == 1
