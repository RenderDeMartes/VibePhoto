"""GUI tests for the histogram's clipping indicators."""

from __future__ import annotations

import os

import numpy as np
import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from vibephoto.ui.histogram import HistogramWidget

pytestmark = pytest.mark.gui


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_no_clipping_on_a_midtone_image(qapp: QApplication) -> None:
    hist = HistogramWidget()
    hist.set_image(np.full((40, 40, 3), 128, dtype=np.uint8))
    assert hist._clip_color(hist._clip_high) is None
    assert hist._clip_color(hist._clip_low) is None


def test_highlight_clipping_lights_white_when_all_channels_blow(qapp: QApplication) -> None:
    hist = HistogramWidget()
    img = np.full((40, 40, 3), 128, dtype=np.uint8)
    img[:10] = 255  # a chunk of fully-white (all channels clipped) pixels
    hist.set_image(img)
    colour = hist._clip_color(hist._clip_high)
    assert colour == QColor(255, 255, 255)
    assert hist._clip_color(hist._clip_low) is None


def test_single_channel_clip_tints_the_indicator(qapp: QApplication) -> None:
    hist = HistogramWidget()
    img = np.full((40, 40, 3), 128, dtype=np.uint8)
    img[:10, :, 2] = 255  # only the blue channel clips
    hist.set_image(img)
    colour = hist._clip_color(hist._clip_high)
    assert colour == QColor(0, 0, 255)


def test_shadow_clipping_detected(qapp: QApplication) -> None:
    hist = HistogramWidget()
    img = np.full((40, 40, 3), 128, dtype=np.uint8)
    img[:10] = 0  # crushed blacks
    hist.set_image(img)
    assert hist._clip_color(hist._clip_low) == QColor(255, 255, 255)


def test_clear_resets_clipping(qapp: QApplication) -> None:
    hist = HistogramWidget()
    hist.set_image(np.full((10, 10, 3), 255, dtype=np.uint8))
    hist.clear()
    assert hist._clip_color(hist._clip_high) is None
