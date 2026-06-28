"""Tests for the headless processing engine: buffer, ops, edit state, pipeline."""

from __future__ import annotations

import numpy as np
import pytest

from vibephoto.processing.color import linear_to_srgb, rgb_to_hsv, srgb_to_linear
from vibephoto.processing.edit_state import EditState
from vibephoto.processing.image_buffer import ImageBuffer
from vibephoto.processing.pipeline import PipelineRenderer, build_stages


@pytest.fixture
def gradient() -> ImageBuffer:
    """A smooth RGB gradient buffer to exercise the operators on real variation."""
    h, w = 64, 96
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    data = np.stack([xx / w, yy / h, np.full((h, w), 0.5, np.float32)], axis=-1).astype(np.float32)
    return ImageBuffer(data)


# -- color + buffer ------------------------------------------------------- #


def test_srgb_roundtrip_is_stable() -> None:
    x = np.linspace(0, 1, 50, dtype=np.float32).reshape(-1, 1, 1).repeat(3, axis=-1)
    back = linear_to_srgb(srgb_to_linear(x))
    assert np.allclose(x, back, atol=1e-4)


def test_image_buffer_uint8_roundtrip() -> None:
    arr = (np.random.default_rng(0).random((10, 12, 3)) * 255).astype(np.uint8)
    buffer = ImageBuffer.from_uint8(arr)
    assert buffer.data.dtype == np.float32 and buffer.data.min() >= 0.0
    assert np.array_equal(buffer.to_uint8(), arr)


def test_to_uint8_clips_out_of_range() -> None:
    data = np.array([[[-0.5, 0.5, 2.0]]], dtype=np.float32)
    out = ImageBuffer(data).to_uint8()
    assert out[0, 0, 0] == 0 and out[0, 0, 2] == 255


# -- pipeline / edit state ------------------------------------------------ #


def test_identity_edit_is_a_noop(gradient: ImageBuffer) -> None:
    out = PipelineRenderer(gradient).render(EditState())
    assert np.allclose(out.data, gradient.data)


def test_draft_pipeline_drops_blur_heavy_stages() -> None:
    full = {s.name for s in build_stages()}
    draft = {s.name for s in build_stages(draft=True)}
    dropped = full - draft
    assert {"sharpen", "noise", "clarity", "texture", "grain"} <= dropped
    assert "exposure" in draft and "tone" in draft  # cheap tone stages stay


def test_draft_render_ignores_sharpening_but_keeps_exposure(gradient: ImageBuffer) -> None:
    # Draft skips Sharpening (a skipped stage) → no effect; Exposure still applies.
    draft_sharp = PipelineRenderer(gradient, draft=True).render(EditState(sharpen_amount=150))
    draft_none = PipelineRenderer(gradient, draft=True).render(EditState())
    assert np.allclose(draft_sharp.data, draft_none.data)  # sharpening deferred to full
    brighter = PipelineRenderer(gradient, draft=True).render(EditState(exposure=1.0))
    assert float(brighter.data.mean()) > float(draft_none.data.mean())


def test_pipeline_covers_every_edit_state_field(gradient: ImageBuffer) -> None:
    # Guard against a parameter that no stage reads (a silent dead control).
    # Union both fronts: temp/tint live in the display chain, wb_kelvin/wb_tint in
    # the scene-linear (RAW) chain.
    keyed = {key for stage in build_stages() for key in stage.keys}
    keyed |= {key for stage in build_stages(linear_scene=True) for key in stage.keys}
    missing = set(EditState().to_dict()) - keyed
    assert not missing, f"EditState fields not wired into any stage: {missing}"


def test_exposure_brightens_and_darkens(gradient: ImageBuffer) -> None:
    base_mean = float(gradient.data.mean())
    up = PipelineRenderer(gradient).render(EditState(exposure=1.0))
    down = PipelineRenderer(gradient).render(EditState(exposure=-1.0))
    assert float(up.data.mean()) > base_mean > float(down.data.mean())


def test_saturation_changes_colorfulness(gradient: ImageBuffer) -> None:
    base_sat = float(rgb_to_hsv(gradient.data)[..., 1].mean())
    desaturated = PipelineRenderer(gradient).render(EditState(saturation=-100))
    assert float(rgb_to_hsv(desaturated.data)[..., 1].mean()) < base_sat


def test_grayscale_produces_neutral_pixels(gradient: ImageBuffer) -> None:
    out = PipelineRenderer(gradient).render(EditState(grayscale=True)).data
    assert np.allclose(out[..., 0], out[..., 1]) and np.allclose(out[..., 1], out[..., 2])


def test_white_balance_warm_shifts_red_above_blue(gradient: ImageBuffer) -> None:
    warm = PipelineRenderer(gradient).render(EditState(temp=80)).data
    assert float(warm[..., 0].mean()) > float(warm[..., 2].mean())


def test_vignette_darkens_corners_not_centre(gradient: ImageBuffer) -> None:
    out = PipelineRenderer(gradient).render(EditState(vignette_amount=-80)).data
    h, w, _ = out.shape
    corner = float(out[0, 0].mean())
    centre = float(out[h // 2, w // 2].mean())
    base_centre = float(gradient.data[h // 2, w // 2].mean())
    assert corner < centre and abs(centre - base_centre) < 0.05


def test_output_stays_in_unit_range(gradient: ImageBuffer) -> None:
    extreme = EditState(exposure=4, contrast=100, whites=100, clarity=100, vibrance=100)
    out = PipelineRenderer(gradient).render(extreme).data
    assert out.min() >= 0.0 and out.max() <= 1.0


# -- memoization ---------------------------------------------------------- #


def test_memoized_render_matches_fresh_render(gradient: ImageBuffer) -> None:
    # A renderer that has cached an earlier edit must produce identical pixels to a
    # cold renderer for a new edit that only changes a downstream stage.
    renderer = PipelineRenderer(gradient)
    renderer.render(EditState(exposure=0.5, vignette_amount=-30))
    warm = renderer.render(EditState(exposure=0.5, vignette_amount=-60))
    cold = PipelineRenderer(gradient).render(EditState(exposure=0.5, vignette_amount=-60))
    assert np.array_equal(warm.data, cold.data)


def test_repeated_identical_render_returns_same_object(gradient: ImageBuffer) -> None:
    renderer = PipelineRenderer(gradient)
    first = renderer.render(EditState(contrast=20))
    second = renderer.render(EditState(contrast=20))
    assert first is second  # fully cached: nothing recomputed


# -- serialisation -------------------------------------------------------- #


def test_edit_state_roundtrips_through_dict() -> None:
    state = EditState(exposure=1.5, contrast=20, grayscale=True)
    state.hsl_sat["red"] = -40
    state.curve_rgb = [(0, 10), (255, 245)]
    restored = EditState.from_dict(state.to_dict())
    assert restored.to_dict() == state.to_dict()
    assert restored.hsl_sat["red"] == -40
    assert restored.curve_rgb == [(0, 10), (255, 245)]


def test_from_dict_ignores_unknown_keys_and_fills_defaults() -> None:
    state = EditState.from_dict({"exposure": 2.0, "not_a_real_field": 9})
    assert state.exposure == 2.0
    assert state.contrast == 0.0  # default preserved


def test_is_identity() -> None:
    assert EditState().is_identity()
    assert not EditState(exposure=0.1).is_identity()
