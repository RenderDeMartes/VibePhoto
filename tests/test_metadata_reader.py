"""Tests for the Pillow-based metadata reader."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from vibephoto.metadata.reader import MetadataReader


def test_reads_dimensions_and_exif(make_jpeg, tmp_path: Path) -> None:
    path = make_jpeg(tmp_path / "a.jpg", size=(640, 480), make="Canon", model="EOS R5")
    info = MetadataReader().read(path)
    assert (info.width, info.height) == (640, 480)
    assert info.camera_make == "Canon"
    assert info.camera_model == "EOS R5"
    assert info.capture_time == datetime(2024, 1, 15, 10, 30, 0)


def test_orientation_read(make_jpeg, tmp_path: Path) -> None:
    path = make_jpeg(tmp_path / "a.jpg", orientation=6)
    assert MetadataReader().read(path).orientation == 6


def test_missing_datetime_is_none(make_jpeg, tmp_path: Path) -> None:
    path = make_jpeg(tmp_path / "a.jpg", datetime_=None)
    assert MetadataReader().read(path).capture_time is None


def test_non_image_degrades_gracefully(tmp_path: Path) -> None:
    bogus = tmp_path / "notimage.jpg"
    bogus.write_bytes(b"this is not a jpeg")
    info = MetadataReader().read(bogus)  # must not raise
    assert info.width is None
    assert info.camera_model is None
