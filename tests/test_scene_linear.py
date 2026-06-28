"""Tests for the scene-linear RAW develop front-end.

Pure NumPy + pipeline (no Qt): the linear operators, the base tone-map, and the
fact that the pipeline runs the linear front-end only for a scene-linear base.
"""

from __future__ import annotations

import numpy as np

from vibephoto.processing import scene_linear
from vibephoto.processing.color import linear_to_srgb
from vibephoto.processing.edit_state import EditState
from vibephoto.processing.image_buffer import ImageBuffer
from vibephoto.processing.pipeline import PipelineRenderer, build_stages
from vibephoto.processing.resample import downscale_buffer


def _flat(value: float, size: int = 4) -> np.ndarray:
    return np.full((size, size, 3), value, dtype=np.float32)


# -- linear operators ------------------------------------------------------ #


def test_exposure_linear_is_a_true_stop() -> None:
    out = scene_linear.exposure_linear(_flat(0.2), 1.0)
    assert np.allclose(out, 0.4)  # +1 EV doubles linear light


def test_exposure_linear_keeps_headroom_above_one() -> None:
    out = scene_linear.exposure_linear(_flat(0.6), 1.0)
    assert float(out.max()) > 1.0  # not clipped — highlights survive to the tone-map


def test_white_balance_kelvin_is_identity_at_reference() -> None:
    rgb = _flat(0.5)
    out = scene_linear.white_balance_kelvin(rgb, scene_linear.WB_REFERENCE_K, 0.0)
    assert np.allclose(out, rgb)  # 6500 K + 0 tint = as-shot, no change


def test_white_balance_kelvin_warms_with_higher_temperature() -> None:
    rgb = _flat(0.5)
    warm = scene_linear.white_balance_kelvin(rgb, 9000.0, 0.0)
    cool = scene_linear.white_balance_kelvin(rgb, 4000.0, 0.0)
    # Higher Kelvin warms (more red, less blue) relative to lower Kelvin.
    assert float(warm[..., 0].mean()) > float(cool[..., 0].mean())
    assert float(warm[..., 2].mean()) < float(cool[..., 2].mean())


def test_blackbody_rgb_is_warmer_at_low_kelvin() -> None:
    warm = scene_linear.blackbody_rgb(3000.0)
    cool = scene_linear.blackbody_rgb(12000.0)
    assert warm[0] / warm[2] > cool[0] / cool[2]  # low K = more red-than-blue


def test_solve_white_balance_neutralises_a_cast() -> None:
    # A bluish pixel should solve to a cooler Kelvin so its gains warm it to neutral.
    bluish = np.array([0.4, 0.5, 0.8], dtype=np.float32)
    kelvin, tint = scene_linear.solve_white_balance(bluish)
    gains = scene_linear._wb_gains(kelvin, tint)
    balanced = bluish * gains
    # After balancing, red and blue are far closer than before.
    assert abs(balanced[0] - balanced[2]) < abs(bluish[0] - bluish[2])


def test_tone_linear_recovers_highlights() -> None:
    bright = _flat(0.7)
    recovered = scene_linear.tone_linear(bright, highlights=-100.0, shadows=0.0,
                                         whites=0.0, blacks=0.0)
    assert recovered.mean() < bright.mean()


def test_tone_linear_lifts_shadows() -> None:
    dark = _flat(0.03)
    lifted = scene_linear.tone_linear(dark, highlights=0.0, shadows=100.0,
                                      whites=0.0, blacks=0.0)
    assert lifted.mean() > dark.mean()


# -- base tone-map --------------------------------------------------------- #


def test_reconstruct_highlights_is_identity_at_zero() -> None:
    rgb = np.array([[[1.0, 0.9, 0.7]]], dtype=np.float32)
    assert np.allclose(scene_linear.reconstruct_highlights(rgb, 0.0), rgb)


def test_reconstruct_highlights_desaturates_a_blown_pixel() -> None:
    # A clipped pixel with a colour cast (red maxed, blue lower) should move toward
    # neutral white when reconstructed.
    rgb = np.array([[[1.0, 0.95, 0.6]]], dtype=np.float32)
    out = scene_linear.reconstruct_highlights(rgb, 100.0)
    spread_before = float(rgb.max() - rgb.min())
    spread_after = float(out.max() - out.min())
    assert spread_after < spread_before  # channels pulled together (toward white)


def test_reconstruct_highlights_leaves_midtones_untouched() -> None:
    rgb = np.array([[[0.4, 0.3, 0.2]]], dtype=np.float32)  # below the highlight zone
    assert np.allclose(scene_linear.reconstruct_highlights(rgb, 100.0), rgb)


def test_tonemap_is_monotonic_and_bounded() -> None:
    ramp = np.linspace(0.0, 1.5, 64, dtype=np.float32).reshape(1, 64, 1).repeat(3, axis=2)
    out = scene_linear.tonemap(ramp)
    flat = out[0, :, 0]
    assert float(out.min()) >= 0.0 and float(out.max()) <= 1.0
    assert np.all(np.diff(flat) >= -1e-6)  # non-decreasing


def test_tonemap_passes_midtones_then_rolls_off_highlights() -> None:
    # Middle grey (the toe's anchor pivot) maps like a plain sRGB encode (~0.46),
    # so the filmic toe adds shadow density without shifting exposure.
    mid = scene_linear.tonemap(_flat(0.18))
    assert abs(float(mid.mean()) - float(linear_to_srgb(_flat(0.18)).mean())) < 1e-4
    # A full-white linear value is shouldered below 1.0 (smooth highlight roll-off).
    white = scene_linear.tonemap(_flat(1.0))
    assert float(white.mean()) < 1.0


def test_tonemap_toe_deepens_shadows_below_grey() -> None:
    # Deep shadows open darker than a plain gamma encode (the filmic density that
    # gives a RAW a familiar, professional "punch" instead of a flat default).
    dark = _flat(0.04)
    out = scene_linear.tonemap(dark)
    plain = linear_to_srgb(dark)
    assert float(out.mean()) < float(plain.mean())


def test_tonemap_toe_leaves_grey_and_above_anchored() -> None:
    # The toe is a no-op at and above the middle-grey pivot: nothing brighter than
    # grey is darkened by it (highlights are shaped only by the shoulder).
    for value in (0.18, 0.4, 0.7):
        toned = scene_linear.tonemap(_flat(value))
        plain = linear_to_srgb(_flat(value))
        assert float(toned.mean()) <= float(plain.mean()) + 1e-6
        if value == 0.18:
            assert abs(float(toned.mean()) - float(plain.mean())) < 1e-4


# -- pipeline selection by colorspace -------------------------------------- #


def test_build_stages_linear_has_tonemap_front() -> None:
    linear = [s.name for s in build_stages(linear_scene=True)]
    display = [s.name for s in build_stages(linear_scene=False)]
    assert "wb_kelvin" in linear and "tonemap" in linear
    assert "white_balance" in display and "tonemap" not in display


def test_renderer_develops_linear_base_to_srgb() -> None:
    base = ImageBuffer(_flat(0.18), "linear")
    out = PipelineRenderer(base).render(EditState())  # identity = "just develop it"
    assert out.colorspace == "srgb"
    # Developed mid-grey ≈ sRGB(0.18) ≈ 0.46, i.e. brighter than the raw linear 0.18.
    assert abs(float(out.data.mean()) - float(linear_to_srgb(_flat(0.18)).mean())) < 1e-3


def test_renderer_leaves_srgb_base_in_display_space() -> None:
    base = ImageBuffer(_flat(0.18), "srgb")
    out = PipelineRenderer(base).render(EditState())  # identity display edit = no-op
    assert out.colorspace == "srgb"
    assert abs(float(out.data.mean()) - 0.18) < 1e-4  # unchanged, no tone-map applied


def test_linear_exposure_gives_more_range_than_display() -> None:
    # The same +1 EV: in linear a near-clipping value recovers detail under -exposure,
    # which a display-space (already-clipped) edit cannot. Sanity-check linearity here.
    base = ImageBuffer(_flat(0.5), "linear")
    brighter = PipelineRenderer(base).render(EditState(exposure=1.0))
    darker = PipelineRenderer(base).render(EditState(exposure=-1.0))
    assert float(brighter.data.mean()) > float(darker.data.mean())


# -- resample preserves linear data ---------------------------------------- #


def test_downscale_buffer_preserves_colorspace() -> None:
    base = ImageBuffer(_flat(0.4, size=64), "linear")
    small = downscale_buffer(base, 16)
    assert small.colorspace == "linear"
    assert max(small.width, small.height) == 16
    assert small.data.dtype == np.float32


def test_downscale_buffer_keeps_float_precision() -> None:
    # A smooth linear gradient retains sub-8-bit values after downscale (a uint8
    # round trip would quantise these to /255 steps).
    grad = np.linspace(0.0, 0.05, 64, dtype=np.float32).reshape(1, 64, 1).repeat(3, axis=2)
    grad = np.repeat(grad, 8, axis=0)
    out = downscale_buffer(ImageBuffer(grad, "linear"), 16)
    assert float(out.data.max()) < 0.06  # values stayed in the tiny linear range
    assert not np.allclose(out.data * 255.0, np.round(out.data * 255.0))  # not quantised


def test_from_uint16_tags_colorspace_and_scales() -> None:
    arr = np.full((2, 2, 3), 65535, dtype=np.uint16)
    buf = ImageBuffer.from_uint16(arr, colorspace="linear")
    assert buf.colorspace == "linear"
    assert np.allclose(buf.data, 1.0)


# -- white-balance EditState fields ---------------------------------------- #


def test_wb_fields_default_to_reference_and_survive_roundtrip() -> None:
    state = EditState()
    assert state.wb_kelvin == scene_linear.WB_REFERENCE_K
    assert state.wb_tint == 0.0
    assert state.is_identity()  # defaults are a no-op edit

    edited = EditState(wb_kelvin=4200.0, wb_tint=15.0)
    assert not edited.is_identity()
    restored = EditState.from_dict(edited.to_dict())
    assert restored.wb_kelvin == 4200.0 and restored.wb_tint == 15.0


def test_renderer_applies_kelvin_only_for_linear_base() -> None:
    warm_state = EditState(wb_kelvin=9000.0)
    linear = ImageBuffer(_flat(0.4), "linear")
    srgb = ImageBuffer(_flat(0.4), "srgb")
    # On a linear (RAW) base the Kelvin WB warms the image; on an sRGB base it is
    # ignored (display path uses temp/tint instead), so the frame is unchanged.
    warmed = PipelineRenderer(linear).render(warm_state)
    neutral = PipelineRenderer(linear).render(EditState())
    assert float(warmed.data[..., 0].mean()) > float(neutral.data[..., 0].mean())
    untouched = PipelineRenderer(srgb).render(warm_state)
    assert np.allclose(untouched.data, _flat(0.4))
