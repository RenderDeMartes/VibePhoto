"""Integration tests for the image loader + develop engine (real pixels)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from vibephoto.processing.edit_state import EditState
from vibephoto.processing.engine import DevelopEngine
from vibephoto.processing.loader import ImageLoader
from vibephoto.raw.service import RawService

_FIXTURE_DNG = Path(__file__).parent / "data" / "synthetic.dng"


def _engine() -> DevelopEngine:
    return DevelopEngine(ImageLoader(RawService()))


def test_loads_and_downsizes_a_jpeg(make_jpeg, tmp_path: Path) -> None:
    src = make_jpeg(tmp_path / "a.jpg", size=(2400, 1600))
    buffer = ImageLoader(RawService()).load(src, is_raw=False, long_edge=800)
    assert buffer is not None
    assert max(buffer.width, buffer.height) == 800  # downsized to the preview edge
    assert buffer.data.dtype == np.float32


def test_loads_respecting_orientation(make_jpeg, tmp_path: Path) -> None:
    # Orientation 6 (rotate 90°) should swap the displayed aspect ratio.
    src = make_jpeg(tmp_path / "rot.jpg", size=(400, 200), orientation=6)
    buffer = ImageLoader(RawService()).load(src, is_raw=False, long_edge=0)
    assert buffer is not None and buffer.height > buffer.width


def test_engine_opens_and_renders(make_jpeg, tmp_path: Path) -> None:
    src = make_jpeg(tmp_path / "b.jpg", size=(600, 400), color=(120, 120, 120))
    renderer = _engine().open(src, is_raw=False, long_edge=400)
    assert renderer is not None
    brighter = renderer.render(EditState(exposure=1.0))
    assert float(brighter.data.mean()) > float(renderer.base.data.mean())


def test_engine_returns_none_for_unreadable_file(tmp_path: Path) -> None:
    bogus = tmp_path / "x.jpg"
    bogus.write_bytes(b"not an image")
    assert _engine().open(bogus, is_raw=False) is None


def test_loads_raw_via_real_demosaic() -> None:
    if not _FIXTURE_DNG.is_file() or not RawService().available:
        import pytest

        pytest.skip("synthetic DNG fixture or rawpy unavailable")
    # RAW now loads through the real LibRaw demosaic (16-bit -> float), not the
    # camera's flattened JPEG preview.
    buffer = ImageLoader(RawService()).load(_FIXTURE_DNG, is_raw=True, long_edge=128)
    assert buffer is not None
    assert buffer.width > 0 and buffer.height > 0
    assert buffer.data.dtype == np.float32
    assert buffer.colorspace == "linear"  # scene-linear, developed by the pipeline
