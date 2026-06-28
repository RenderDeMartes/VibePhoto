"""Tests for Auto Edit / Auto HDR adjustments."""

from __future__ import annotations

import numpy as np

from vibephoto.processing.auto import auto_hdr, auto_tone
from vibephoto.processing.image_buffer import ImageBuffer
from vibephoto.processing.layered_renderer import render_stack
from vibephoto.processing.layers import LayerStack


def _flat(value: float) -> ImageBuffer:
    return ImageBuffer(np.full((30, 40, 3), value, dtype=np.float32))


def test_auto_tone_brightens_dark_and_darkens_bright() -> None:
    assert auto_tone(_flat(0.15)).exposure > 0
    assert auto_tone(_flat(0.9)).exposure < 0


def test_auto_tone_actually_improves_brightness() -> None:
    base = _flat(0.15)
    out = render_stack(base, LayerStack.single(auto_tone(base)))
    assert float(out.data.mean()) > float(base.data.mean())


def test_auto_hdr_has_strong_shadow_highlight_and_clarity() -> None:
    state = auto_hdr(_flat(0.3))
    assert state.highlights <= -70 and state.shadows >= 60 and state.clarity > 0
