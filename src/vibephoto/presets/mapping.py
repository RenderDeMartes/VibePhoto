"""Shared mapping from Camera Raw ``crs:`` settings to an :class:`EditState`.

Both preset formats Vibe Photo reads — standard ``.xmp`` (XML) and legacy
``.lrtemplate`` (Lua) — use the same ``crs:`` parameter names; they only differ in
how those name→value pairs are stored. Each parser flattens its file into a
``{name: value}`` dict and hands it here, so the actual look-mapping lives in one
place. Values may be strings (XMP) or numbers/lists (Lua); the coercers tolerate
both. Unknown fields are ignored, so presets using features Vibe Photo doesn't
model yet still import cleanly.
"""

from __future__ import annotations

from typing import Any

from vibephoto.processing.edit_state import HSL_BANDS, EditState

#: HSL/B&W band -> professional RAW editors suffix (their tag spelling).
_BAND_SUFFIX = {
    "red": "Red",
    "orange": "Orange",
    "yellow": "Yellow",
    "green": "Green",
    "aqua": "Aqua",
    "blue": "Blue",
    "purple": "Purple",
    "magenta": "Magenta",
}


class PresetParseError(ValueError):
    """Raised when a preset file cannot be parsed."""


def _num(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


def _bool(value: Any) -> bool:
    return str(value).strip().lower() == "true"


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _first(values: dict[str, Any], keys: tuple[str, ...], default: float = 0.0) -> float:
    for key in keys:
        if key in values:
            return _num(values[key], default)
    return default


def _curve(value: Any) -> list[tuple[int, int]]:
    """Parse a tone curve from XMP (``["x, y", …]``) or Lua (flat ``[x0, y0, …]``)."""
    if not isinstance(value, list) or not value:
        return []
    if isinstance(value[0], str) and "," in value[0]:  # XMP: list of "x, y" strings
        points: list[tuple[int, int]] = []
        for item in value:
            parts = str(item).split(",")
            if len(parts) == 2:
                try:
                    points.append((int(float(parts[0])), int(float(parts[1]))))
                except ValueError:
                    continue
        return points
    nums: list[int] = []  # Lua: flat list of numbers [x0, y0, x1, y1, …]
    for item in value:
        try:
            nums.append(int(float(item)))
        except (TypeError, ValueError):
            continue
    return list(zip(nums[0::2], nums[1::2], strict=False))


def to_edit_state(values: dict[str, Any]) -> EditState:
    """Map a flat ``crs:`` settings dict onto an :class:`EditState`."""
    state = EditState()

    # White balance: absolute Kelvin/Tint -> relative sliders (approximate).
    if "Temperature" in values:
        state.temp = _clamp((_num(values["Temperature"], 5500.0) - 5500.0) / 80.0, -100.0, 100.0)
    state.tint = _clamp(_num(values.get("Tint")), -100.0, 100.0)

    # Basic tone + presence.
    state.exposure = _clamp(_num(values.get("Exposure2012")), -5.0, 5.0)
    state.contrast = _num(values.get("Contrast2012"))
    state.highlights = _num(values.get("Highlights2012"))
    state.shadows = _num(values.get("Shadows2012"))
    state.whites = _num(values.get("Whites2012"))
    state.blacks = _num(values.get("Blacks2012"))
    state.texture = _num(values.get("Texture"))
    state.clarity = _num(values.get("Clarity2012"))
    state.dehaze = _num(values.get("Dehaze"))
    state.vibrance = _num(values.get("Vibrance"))
    state.saturation = _num(values.get("Saturation"))

    # Parametric curve regions.
    state.park_highlights = _num(values.get("ParametricHighlights"))
    state.park_lights = _num(values.get("ParametricLights"))
    state.park_darks = _num(values.get("ParametricDarks"))
    state.park_shadows = _num(values.get("ParametricShadows"))

    # Point tone curves.
    state.curve_rgb = _curve(values.get("ToneCurvePV2012"))
    state.curve_red = _curve(values.get("ToneCurvePV2012Red"))
    state.curve_green = _curve(values.get("ToneCurvePV2012Green"))
    state.curve_blue = _curve(values.get("ToneCurvePV2012Blue"))

    # HSL + B&W mixer per band.
    for band in HSL_BANDS:
        suffix = _BAND_SUFFIX[band]
        state.hsl_hue[band] = _num(values.get(f"HueAdjustment{suffix}"))
        state.hsl_sat[band] = _num(values.get(f"SaturationAdjustment{suffix}"))
        state.hsl_lum[band] = _num(values.get(f"LuminanceAdjustment{suffix}"))
        state.bw_mix[band] = _num(values.get(f"GrayMixer{suffix}"))
    state.grayscale = _bool(values.get("ConvertToGrayscale"))

    # Color grading (prefer ColorGrade*, fall back to legacy SplitToning*).
    state.grade_shadow_hue = _first(values, ("ColorGradeShadowHue", "SplitToningShadowHue"))
    state.grade_shadow_sat = _first(
        values, ("ColorGradeShadowSat", "SplitToningShadowSaturation")
    )
    state.grade_shadow_lum = _num(values.get("ColorGradeShadowLum"))
    state.grade_mid_hue = _num(values.get("ColorGradeMidtoneHue"))
    state.grade_mid_sat = _num(values.get("ColorGradeMidtoneSat"))
    state.grade_mid_lum = _num(values.get("ColorGradeMidtoneLum"))
    state.grade_highlight_hue = _first(
        values, ("ColorGradeHighlightHue", "SplitToningHighlightHue")
    )
    state.grade_highlight_sat = _first(
        values, ("ColorGradeHighlightSat", "SplitToningHighlightSaturation")
    )
    state.grade_highlight_lum = _num(values.get("ColorGradeHighlightLum"))
    state.grade_global_hue = _num(values.get("ColorGradeGlobalHue"))
    state.grade_global_sat = _num(values.get("ColorGradeGlobalSat"))
    state.grade_balance = _first(values, ("ColorGradeBalance", "SplitToningBalance"))
    if "ColorGradeBlending" in values:
        state.grade_blending = _num(values["ColorGradeBlending"], 50.0)

    # Detail + effects.
    state.sharpen_amount = _num(values.get("Sharpness"))
    state.sharpen_radius = _num(values.get("SharpenRadius"), 1.0)
    state.sharpen_detail = _num(values.get("SharpenDetail"), 25.0)
    state.sharpen_masking = _num(values.get("SharpenEdgeMasking"))
    state.noise_luminance = _num(values.get("LuminanceSmoothing"))
    state.noise_color = _num(values.get("ColorNoiseReduction"))
    state.vignette_amount = _num(values.get("PostCropVignetteAmount"))
    if "PostCropVignetteMidpoint" in values:
        state.vignette_midpoint = _num(values["PostCropVignetteMidpoint"], 50.0)
    state.grain_amount = _num(values.get("GrainAmount"))

    return state
