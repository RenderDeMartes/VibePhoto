"""Tests for creative/camera base-look profiles."""

from __future__ import annotations

import numpy as np

from vibephoto.processing.color import rgb_to_hsv
from vibephoto.processing.edit_state import EditState
from vibephoto.processing.image_buffer import ImageBuffer
from vibephoto.processing.pipeline import PipelineRenderer
from vibephoto.processing.profiles import (
    DEFAULT_PROFILE,
    PROFILE_NAMES,
    apply_profile,
)


def _img(value: float = 0.5) -> np.ndarray:
    rng = np.random.default_rng(0)
    return (rng.random((16, 16, 3)).astype(np.float32) * 0.6 + value - 0.3).clip(0, 1)


def test_neutral_profile_is_identity() -> None:
    img = _img()
    assert np.allclose(apply_profile(img, DEFAULT_PROFILE), img)
    assert np.allclose(apply_profile(img, "Unknown"), img)  # unknown = no-op


def test_vivid_increases_saturation() -> None:
    img = _img()
    base_sat = float(rgb_to_hsv(img)[..., 1].mean())
    vivid_sat = float(rgb_to_hsv(apply_profile(img, "Vivid"))[..., 1].mean())
    assert vivid_sat > base_sat


def test_flat_reduces_contrast() -> None:
    img = _img()
    base_std = float(img.std())
    flat_std = float(apply_profile(img, "Flat").std())
    assert flat_std < base_std  # flatter = lower spread


def test_monochrome_desaturates() -> None:
    out = apply_profile(_img(), "Monochrome")
    assert np.allclose(out[..., 0], out[..., 1], atol=1e-5)  # R==G==B → grey


def test_matte_lifts_blacks() -> None:
    dark = np.zeros((4, 4, 3), dtype=np.float32)
    assert float(apply_profile(dark, "Matte").min()) > 0.0  # blacks lifted off zero


def test_profile_default_keeps_edit_identity() -> None:
    assert EditState().profile == DEFAULT_PROFILE
    assert EditState().is_identity()
    assert not EditState(profile="Vivid").is_identity()


def test_profile_runs_in_pipeline_for_srgb_and_roundtrips() -> None:
    base = ImageBuffer(_img().astype(np.float32), "srgb")
    neutral = PipelineRenderer(base).render(EditState())
    vivid = PipelineRenderer(base).render(EditState(profile="Vivid"))
    assert not np.allclose(neutral.data, vivid.data)  # profile changes the render
    restored = EditState.from_dict(EditState(profile="Landscape").to_dict())
    assert restored.profile == "Landscape"
    assert "Neutral" in PROFILE_NAMES and len(PROFILE_NAMES) >= 6
