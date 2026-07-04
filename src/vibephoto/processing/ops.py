"""Adjustment operators — the pixel math behind each develop control.

Every function is pure: it takes a ``float32`` RGB array shaped ``(H, W, 3)`` in
``[0, 1]`` plus scalar parameters and returns a new array, never mutating its
input. Each is a no-op at its neutral parameter value, so the renderer can skip
unchanged stages cheaply. The implementations favour clear, correct-direction
results over bit-exact professional RAW editors parity (documented where they simplify), and run
on the CPU via NumPy — the backend seam in ``docs/06`` lets a GPU kernel replace
any of them later without touching callers.
"""

from __future__ import annotations

import numpy as np

from vibephoto.processing.color import (
    Array,
    apply_lut,
    clip01,
    gaussian_blur,
    hsv_to_rgb,
    linear_to_srgb,
    luminance,
    lut_from_points,
    rgb_to_hsv,
    srgb_to_linear,
)
from vibephoto.processing.edit_state import HSL_BANDS

# Hue centres (degrees) for the eight HSL / B&W bands.
_HUE_CENTERS: dict[str, float] = {
    "red": 0.0,
    "orange": 30.0,
    "yellow": 60.0,
    "green": 120.0,
    "aqua": 180.0,
    "blue": 240.0,
    "purple": 270.0,
    "magenta": 300.0,
}
_BAND_HALFWIDTH = 50.0  # degrees of influence either side of a band centre


def white_balance(rgb: Array, temp: float, tint: float) -> Array:
    """Relative white balance. ``temp``/``tint`` in -100..100; 0 = as-shot."""
    if temp == 0.0 and tint == 0.0:
        return rgb
    t, ti = temp / 100.0, tint / 100.0
    gains = np.array([1.0 + 0.5 * t, 1.0 - 0.4 * ti, 1.0 - 0.5 * t], dtype=np.float32)
    return clip01(rgb * gains)


def exposure(rgb: Array, ev: float) -> Array:
    """Exposure in stops, applied in linear light."""
    if ev == 0.0:
        return rgb
    return linear_to_srgb(srgb_to_linear(rgb) * (2.0**ev))


def contrast(rgb: Array, amount: float) -> Array:
    """S-curve contrast about mid-grey. ``amount`` in -100..100."""
    if amount == 0.0:
        return rgb
    factor = 1.0 + (amount / 100.0) * 0.7
    return clip01((rgb - 0.5) * factor + 0.5)


def tone_regions(
    rgb: Array, highlights: float, shadows: float, whites: float, blacks: float
) -> Array:
    """Highlights / Shadows / Whites / Blacks via smooth luminance-range masks."""
    if highlights == 0.0 and shadows == 0.0 and whites == 0.0 and blacks == 0.0:
        return rgb
    lum = luminance(rgb)[..., None]
    out = rgb
    if shadows != 0.0:
        mask = np.clip(1.0 - lum / 0.5, 0.0, 1.0) ** 2
        out = out + (shadows / 100.0) * 0.5 * mask
    if highlights != 0.0:
        mask = np.clip((lum - 0.5) / 0.5, 0.0, 1.0) ** 2
        out = out + (highlights / 100.0) * 0.5 * mask
    if blacks != 0.0:
        mask = np.clip(1.0 - lum / 0.25, 0.0, 1.0) ** 2
        out = out + (blacks / 100.0) * 0.3 * mask
    if whites != 0.0:
        mask = np.clip((lum - 0.7) / 0.3, 0.0, 1.0) ** 2
        out = out + (whites / 100.0) * 0.3 * mask
    return clip01(out)


def local_contrast(rgb: Array, amount: float, sigma_frac: float) -> Array:
    """Unsharp local-contrast on luminance (Clarity / Texture).

    ``sigma_frac`` sets the blur radius relative to the short edge: large for
    Clarity (broad local contrast), small for Texture (fine detail).
    """
    if amount == 0.0:
        return rgb
    short_edge = min(rgb.shape[0], rgb.shape[1])
    sigma = max(1.0, sigma_frac * short_edge)
    lum = luminance(rgb)
    detail = lum - gaussian_blur(lum, sigma)
    return clip01(rgb + (amount / 100.0) * detail[..., None])


def dehaze(rgb: Array, amount: float) -> Array:
    """Simplified dehaze: remove an estimated veil and add contrast + saturation
    (positive), or add atmospheric haze (negative)."""
    if amount == 0.0:
        return rgb
    a = amount / 100.0
    if a > 0.0:
        # Estimate the veil on a subsampled grid — the 85th percentile of the
        # dark channel is statistically identical at 1/16 the pixels.
        veil = float(np.quantile(np.min(rgb[::4, ::4], axis=-1), 0.85))
        out = clip01((rgb - a * veil * 0.5) / max(1e-3, 1.0 - a * veil * 0.5))
        out = contrast(out, a * 30.0)
        return vibrance_saturation(out, 0.0, a * 25.0)
    out = clip01(rgb * (1.0 + a * 0.2) - a * 0.12)
    return vibrance_saturation(out, 0.0, a * 25.0)


def vibrance_saturation(rgb: Array, vibrance: float, saturation: float) -> Array:
    """Saturation (uniform) and Vibrance (protects already-saturated pixels)."""
    if vibrance == 0.0 and saturation == 0.0:
        return rgb
    hsv = rgb_to_hsv(rgb)
    s = hsv[..., 1]
    if saturation != 0.0:
        s = s * (1.0 + saturation / 100.0)
    if vibrance != 0.0:
        s = s * (1.0 + (vibrance / 100.0) * (1.0 - np.clip(s, 0.0, 1.0)))
    hsv[..., 1] = np.clip(s, 0.0, 1.0)
    return hsv_to_rgb(hsv)


def parametric_curve(
    rgb: Array, highlights: float, lights: float, darks: float, shadows: float
) -> Array:
    """Parametric tone curve: four region sliders shape a smooth global curve."""
    if highlights == 0.0 and lights == 0.0 and darks == 0.0 and shadows == 0.0:
        return rgb
    x = np.linspace(0.0, 1.0, 256, dtype=np.float32)
    y = x.copy()
    regions = ((shadows, 0.12, 0.12), (darks, 0.37, 0.18), (lights, 0.63, 0.18),
               (highlights, 0.88, 0.12))
    for amount, center, width in regions:
        if amount != 0.0:
            bump = (amount / 100.0) * 0.22 * np.exp(-((x - center) ** 2) / (2 * width * width))
            y = np.asarray(y + bump, dtype=np.float32)
    y = np.maximum.accumulate(np.clip(y, 0.0, 1.0)).astype(np.float32)
    lut = np.clip(y, 0.0, 1.0).astype(np.float32)
    return apply_lut(rgb, lut)  # one gather over all three channels


def point_curves(
    rgb: Array,
    rgb_pts: list[tuple[int, int]],
    red_pts: list[tuple[int, int]],
    green_pts: list[tuple[int, int]],
    blue_pts: list[tuple[int, int]],
) -> Array:
    """Apply point tone curves: a master (all channels) then per-channel curves.

    The master and per-channel curves are *composed into one LUT per channel*, so
    the image is touched exactly once regardless of how many curves are active.
    """
    master = lut_from_points([(float(x), float(y)) for x, y in rgb_pts]) if rgb_pts else None
    luts: list[Array | None] = []
    for pts in (red_pts, green_pts, blue_pts):
        lut = lut_from_points([(float(x), float(y)) for x, y in pts]) if pts else None
        if lut is not None and master is not None:
            # compose: channel curve applied to the master's output
            lut = lut[np.clip(master * 255.0, 0, 255).astype(np.int32)]
        luts.append(lut if lut is not None else master)
    if all(lut is None for lut in luts):
        return rgb
    out = np.empty_like(rgb)
    for channel, lut in enumerate(luts):
        if lut is None:
            out[..., channel] = rgb[..., channel]
        else:
            out[..., channel] = apply_lut(rgb[..., channel], lut)
    return out.astype(np.float32)


def _angular_distance(hue_deg: Array, center: float) -> Array:
    # abs + min instead of a modulo — same wrap-around distance, ~2x faster.
    out: Array = np.abs(hue_deg - center)
    np.minimum(out, 360.0 - out, out=out)
    return out


def _band_weight(hue_deg: Array, center: float) -> Array:
    out = _angular_distance(hue_deg, center)
    out *= np.float32(-1.0 / _BAND_HALFWIDTH)
    out += np.float32(1.0)
    return np.clip(out, 0.0, 1.0, out=out)


def hsl(
    rgb: Array,
    hue: dict[str, float],
    sat: dict[str, float],
    lum: dict[str, float],
) -> Array:
    """Per-band Hue/Saturation/Luminance, weighted by hue membership x saturation."""
    if not any(v != 0.0 for d in (hue, sat, lum) for v in d.values()):
        return rgb
    hsv = rgb_to_hsv(rgb)
    h_deg = hsv[..., 0] * 360.0
    saturation = hsv[..., 1]
    hue_shift = np.zeros_like(h_deg)
    sat_mul = np.ones_like(h_deg)
    lum_add = np.zeros_like(h_deg)
    for band in HSL_BANDS:
        if hue[band] == 0.0 and sat[band] == 0.0 and lum[band] == 0.0:
            continue  # untouched band — skip its full-frame weight computation
        weight = _band_weight(h_deg, _HUE_CENTERS[band]) * saturation
        if hue[band] != 0.0:
            hue_shift = hue_shift + weight * (hue[band] / 100.0) * 30.0
        if sat[band] != 0.0:
            sat_mul = sat_mul * (1.0 + weight * (sat[band] / 100.0))
        if lum[band] != 0.0:
            lum_add = lum_add + weight * (lum[band] / 100.0) * 0.3
    hsv[..., 0] = ((h_deg + hue_shift) % 360.0) / 360.0
    hsv[..., 1] = np.clip(saturation * sat_mul, 0.0, 1.0)
    hsv[..., 2] = np.clip(hsv[..., 2] + lum_add, 0.0, 1.0)
    return hsv_to_rgb(hsv)


def grayscale(rgb: Array, mix: dict[str, float]) -> Array:
    """Convert to black & white with a per-band luminance mixer."""
    base = luminance(rgb)
    hsv = rgb_to_hsv(rgb)
    h_deg = hsv[..., 0] * 360.0
    saturation = hsv[..., 1]
    adjust = np.zeros_like(base)
    for band in HSL_BANDS:
        if mix[band] != 0.0:
            weight = _band_weight(h_deg, _HUE_CENTERS[band]) * saturation
            adjust = adjust + weight * (mix[band] / 100.0) * 0.5
    gray = clip01(base + adjust)
    return np.stack([gray, gray, gray], axis=-1)


def _tint_color(hue_deg: float, sat: float) -> Array:
    hsv = np.array([[[hue_deg / 360.0, sat, 1.0]]], dtype=np.float32)
    color: Array = hsv_to_rgb(hsv)[0, 0]
    return color


def color_grade(
    rgb: Array,
    shadow: tuple[float, float, float],
    mid: tuple[float, float, float],
    highlight: tuple[float, float, float],
    global_hue: float,
    global_sat: float,
    balance: float,
    blending: float,
) -> Array:
    """Three-way color grading (+ global) via luminance-zone masks.

    Each zone tints toward its hue (weighted by its saturation) and can lift/lower
    that zone's luminance. ``balance`` slides the shadow/highlight split.
    """
    zones = (shadow, mid, highlight)
    if global_sat == 0.0 and all(s == 0.0 and lm == 0.0 for _, s, lm in zones):
        return rgb
    lum = luminance(rgb)
    bal = balance / 100.0
    shadow_mask = np.clip(1.0 - lum / (0.5 + 0.3 * bal), 0.0, 1.0) ** 2
    highlight_mask = np.clip((lum - (0.5 + 0.3 * bal)) / (0.5 - 0.3 * bal + 1e-3), 0.0, 1.0) ** 2
    mid_mask = np.clip(1.0 - np.abs(2.0 * lum - 1.0), 0.0, 1.0)
    strength = 0.3 + 0.7 * (blending / 100.0)
    out = rgb
    for (hue, sat, lum_adj), mask in zip(
        zones, (shadow_mask, mid_mask, highlight_mask), strict=True
    ):
        if sat != 0.0:
            tint = _tint_color(hue, 1.0) - 0.5
            out = out + (sat / 100.0) * strength * mask[..., None] * tint
        if lum_adj != 0.0:
            out = out + (lum_adj / 100.0) * 0.3 * mask[..., None]
    if global_sat != 0.0:
        tint = _tint_color(global_hue, 1.0) - 0.5
        out = out + (global_sat / 100.0) * 0.3 * tint
    return clip01(out)


def sharpen(
    rgb: Array, amount: float, radius: float, detail: float, masking: float
) -> Array:
    """Unsharp-mask sharpening on luminance, with an optional edge mask."""
    if amount <= 0.0:
        return rgb
    lum = luminance(rgb)
    high = lum - gaussian_blur(lum, max(0.5, radius))
    high = high * (0.5 + detail / 100.0)
    if masking > 0.0:
        gx = np.gradient(lum, axis=1)
        gy = np.gradient(lum, axis=0)
        edge = np.sqrt(gx * gx + gy * gy)
        edge = edge / (float(edge.max()) + 1e-6)
        threshold = masking / 100.0
        mask = np.clip((edge - threshold) / (1.0 - threshold + 1e-3), 0.0, 1.0)
        high = high * mask
    return clip01(np.asarray(rgb + (amount / 100.0) * high[..., None], dtype=np.float32))


def noise_reduction(rgb: Array, luminance_amount: float, color_amount: float) -> Array:
    """Light luminance + chroma denoise (blend toward a smoothed version)."""
    if luminance_amount <= 0.0 and color_amount <= 0.0:
        return rgb
    out = rgb
    if color_amount > 0.0:
        hsv = rgb_to_hsv(out)
        blended = (1.0 - color_amount / 100.0) * hsv[..., 1] + (
            color_amount / 100.0
        ) * gaussian_blur(hsv[..., 1], 2.0)
        hsv[..., 1] = np.clip(blended, 0.0, 1.0)
        out = hsv_to_rgb(hsv)
    if luminance_amount > 0.0:
        smoothed = gaussian_blur(out, 1.0)
        blend = luminance_amount / 100.0 * 0.7
        out = clip01((1.0 - blend) * out + blend * smoothed)
    return out


def vignette(rgb: Array, amount: float, midpoint: float) -> Array:
    """Post-crop vignette: negative darkens corners, positive brightens them."""
    if amount == 0.0:
        return rgb
    h, w = rgb.shape[0], rgb.shape[1]
    yy = np.linspace(-1.0, 1.0, h, dtype=np.float32)[:, None]
    xx = np.linspace(-1.0, 1.0, w, dtype=np.float32)[None, :]
    radius = np.sqrt(xx * xx + yy * yy) / np.sqrt(2.0)
    mid = 0.2 + 0.8 * (midpoint / 100.0)
    falloff = np.clip((radius - mid) / (1.0 - mid + 1e-3), 0.0, 1.0) ** 2
    factor = 1.0 + (amount / 100.0) * falloff
    return clip01(rgb * factor[..., None])


#: One cached unit-noise field per (shape, seed) — grain is deterministic, so the
#: expensive RNG draw is reused across renders and only rescaled by ``amount``.
_grain_noise: dict[tuple[int, int, int], Array] = {}


def grain(rgb: Array, amount: float, seed: int = 1234) -> Array:
    """Add monochrome film grain."""
    if amount <= 0.0:
        return rgb
    key = (rgb.shape[0], rgb.shape[1], seed)
    noise = _grain_noise.get(key)
    if noise is None:
        _grain_noise.clear()  # keep at most one field resident (~8 MB at preview size)
        rng = np.random.default_rng(seed)
        noise = rng.standard_normal(rgb.shape[:2]).astype(np.float32)
        _grain_noise[key] = noise
    return clip01(rgb + (noise * ((amount / 100.0) * 0.08))[..., None])
