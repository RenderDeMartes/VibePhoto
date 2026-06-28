"""Unit tests for the RAW decoder registry and RawService orchestration.

These use a fake decoder and need no native RAW toolchain, so they run in the
headless environment (no rawpy). The real rawpy adapter is exercised in
``test_raw_integration.py``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from vibephoto.raw.decoder import (
    DecoderRegistry,
    RawImage,
    RawInspection,
    default_registry,
)
from vibephoto.raw.service import RawService

_RAW_EXTS = {"cr2", "cr3", "nef", "arw", "dng"}


class FakeDecoder:
    """In-memory stand-in for a real RAW decoder (satisfies the RawDecoder Protocol)."""

    name = "fake"

    def __init__(
        self,
        *,
        preview: bytes | None = None,
        width: int = 6000,
        height: int = 4000,
        flip: int = 0,
        rgb: np.ndarray | None = None,
    ) -> None:
        self._preview = preview
        self._width = width
        self._height = height
        self._flip = flip
        self._rgb = rgb

    def handles(self, ext: str) -> bool:
        return ext.lstrip(".").lower() in _RAW_EXTS

    def inspect(self, path: Path) -> RawInspection | None:
        return RawInspection(
            self._preview, self._width, self._height, self._flip,
            camera_wb=(2097.0, 1024.0, 1694.0, 1024.0),
            xyz_to_cam=(
                (0.7034, -0.0804, -0.1014),
                (-0.442, 1.2564, 0.2058),
                (-0.0851, 0.1994, 0.5758),
                (0.0, 0.0, 0.0),
            ),
        )

    def decode(self, path: Path, *, half_size: bool = False) -> RawImage | None:
        if self._rgb is None:
            return None
        return RawImage(self._rgb, int(self._rgb.shape[1]), int(self._rgb.shape[0]))


def _jpeg_bytes(make_jpeg, tmp_path: Path, **kwargs: object) -> bytes:
    return make_jpeg(tmp_path / "preview.jpg", **kwargs).read_bytes()


# -- registry ------------------------------------------------------------- #


def test_registry_selects_by_extension() -> None:
    registry = DecoderRegistry([FakeDecoder()])
    assert registry.decoder_for("cr3") is registry.decoders[0]
    assert registry.decoder_for(".NEF") is registry.decoders[0]  # case + dot tolerant
    assert registry.decoder_for("jpg") is None


def test_empty_registry_is_unavailable() -> None:
    registry = DecoderRegistry()
    assert registry.available is False
    assert registry.decoder_for("cr3") is None


def test_default_registry_constructs() -> None:
    # Must not raise whether or not rawpy is installed.
    assert isinstance(default_registry(), DecoderRegistry)


# -- RawService façade ---------------------------------------------------- #


def test_service_unavailable_when_no_decoders() -> None:
    service = RawService(DecoderRegistry())
    assert service.available is False
    assert service.supports(Path("a.cr3")) is False
    assert service.load_preview(Path("a.cr3")) is None
    assert service.read_metadata(Path("a.cr3")) is None
    assert service.decode(Path("a.cr3")) is None


def test_service_supports_only_raw_extensions() -> None:
    service = RawService(DecoderRegistry([FakeDecoder()]))
    assert service.supports(Path("shoot/IMG.CR3")) is True
    assert service.supports(Path("shoot/IMG.jpg")) is False


def test_load_preview_returns_embedded_bytes() -> None:
    service = RawService(DecoderRegistry([FakeDecoder(preview=b"\xff\xd8jpeg")]))
    assert service.load_preview(Path("a.cr3")) == b"\xff\xd8jpeg"


def test_read_metadata_merges_preview_exif_with_raw_dimensions(
    make_jpeg, tmp_path: Path
) -> None:
    preview = _jpeg_bytes(make_jpeg, tmp_path, size=(800, 600), make="Sony", model="A7 IV")
    service = RawService(
        DecoderRegistry([FakeDecoder(preview=preview, width=7008, height=4672, flip=0)])
    )

    info = service.read_metadata(Path("a.arw"))

    assert info is not None
    # EXIF comes from the preview...
    assert info.camera_make == "Sony"
    assert info.camera_model == "A7 IV"
    # ...but dimensions describe the full-resolution master, not the 800x600 preview.
    assert (info.width, info.height) == (7008, 4672)


@pytest.mark.parametrize(
    ("flip", "expected_orientation"),
    [(0, 1), (3, 3), (5, 8), (6, 6)],
)
def test_libraw_flip_maps_to_exif_orientation_when_preview_has_none(
    make_jpeg, tmp_path: Path, flip: int, expected_orientation: int
) -> None:
    preview = _jpeg_bytes(make_jpeg, tmp_path, orientation=1)  # no rotation in preview
    service = RawService(DecoderRegistry([FakeDecoder(preview=preview, flip=flip)]))
    info = service.read_metadata(Path("a.nef"))
    assert info is not None and info.orientation == expected_orientation


def test_preview_orientation_takes_precedence_over_flip(make_jpeg, tmp_path: Path) -> None:
    preview = _jpeg_bytes(make_jpeg, tmp_path, orientation=8)
    service = RawService(DecoderRegistry([FakeDecoder(preview=preview, flip=6)]))
    info = service.read_metadata(Path("a.nef"))
    assert info is not None and info.orientation == 8


def test_read_metadata_without_preview_still_yields_dimensions() -> None:
    service = RawService(
        DecoderRegistry([FakeDecoder(preview=None, width=5472, height=3648, flip=6)])
    )
    info = service.read_metadata(Path("a.cr2"))
    assert info is not None
    assert (info.width, info.height) == (5472, 3648)
    assert info.orientation == 6
    assert info.camera_make is None  # no preview EXIF to read


def test_decode_returns_raw_image() -> None:
    rgb = np.zeros((4, 6, 3), dtype=np.uint8)
    service = RawService(DecoderRegistry([FakeDecoder(rgb=rgb)]))
    image = service.decode(Path("a.dng"))
    assert image is not None
    assert (image.width, image.height) == (6, 4)
    assert image.rgb.shape == (4, 6, 3)


def test_as_shot_temperature_from_calibration() -> None:
    service = RawService(DecoderRegistry([FakeDecoder()]))
    cct = service.as_shot_temperature(Path("a.cr2"))
    assert cct is not None and 5200 <= cct <= 5500  # daylight from the fake calibration


def test_as_shot_temperature_none_without_decoder() -> None:
    assert RawService(DecoderRegistry()).as_shot_temperature(Path("a.cr2")) is None
