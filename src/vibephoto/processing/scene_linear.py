"""Scene-linear develop front-end — the "develop the RAW, not a JPEG" core.

A RAW is decoded to **scene-linear** light (camera white balance applied, no tone
curve). These operators run in that linear space, where exposure and tone behave
photographically and highlights have real headroom, before :func:`tonemap` maps the
result to display sRGB. The rest of the pipeline (contrast, presence, HSL, curves,
grade, detail, effects) then runs in display space as usual.

Why linear matters: doubling exposure is a single multiply (a true stop), and
pulling Highlights down recovers the smooth roll-off near clipping instead of
fighting an already-baked 8-bit JPEG. This is the difference between developing the
RAW and editing a flattened image.
"""

from __future__ import annotations

import numpy as np

from vibephoto.processing.color import Array, clip01, linear_to_srgb, luminance

#: Highlights begin to roll off above this linear value in the base tone-map.
_SHOULDER_KNEE = 0.75

#: Base tone-map shadow toe. A plain linear→sRGB encode opens a RAW flat and
#: low-contrast; the conventional default profile bakes in shadow density and a
#: highlight shoulder so the RAW opens with "punch". The toe deepens tones below
#: middle grey (anchored *at* middle grey so exposure stays put), giving that
#: filmic contrast without touching midtones or highlights.
_TOE_PIVOT = 0.18  # middle grey (linear) — the toe is a no-op here and above
_TOE_STRENGTH = 0.22  # max shadow darkening, reached toward black

#: White-balance reference (D65). A RAW decodes as-shot-neutral, so this Kelvin
#: value means "no change"; the slider warms/cools relative to it.
WB_REFERENCE_K = 6500.0


def blackbody_rgb(kelvin: float) -> Array:
    """Approximate the RGB of a blackbody at ``kelvin`` (Tanner Helland), in (0, 1].

    A compact daylight-locus approximation used to derive white-balance gains; it
    captures the warm→cool progression well across the photographic range.
    """
    t = min(max(kelvin, 1000.0), 40000.0) / 100.0
    if t <= 66.0:
        red = 255.0
        green = 99.4708025861 * np.log(t) - 161.1195681661
    else:
        red = 329.698727446 * (t - 60.0) ** -0.1332047592
        green = 288.1221695283 * (t - 60.0) ** -0.0755148492
    if t >= 66.0:
        blue = 255.0
    elif t <= 19.0:
        blue = 0.0
    else:
        blue = 138.5177312231 * np.log(t - 10.0) - 305.0447927307
    rgb = np.array([red, green, blue], dtype=np.float32) / 255.0
    clamped: Array = np.clip(rgb, 1e-3, 1.0).astype(np.float32)
    return clamped


def _wb_gains(kelvin: float, tint: float) -> Array:
    """Channel gains that warm/cool a D65-neutral image toward ``kelvin``/``tint``.

    Higher Kelvin warms (boost red, cut blue); ``tint`` > 0 adds magenta (cuts
    green). Normalised to green so overall brightness is roughly preserved.
    """
    gains = blackbody_rgb(WB_REFERENCE_K) / blackbody_rgb(kelvin)
    gains = gains / gains[1]
    gains[1] = gains[1] / (1.0 + (tint / 100.0) * 0.5)
    result: Array = gains.astype(np.float32)
    return result


def white_balance_kelvin(rgb: Array, kelvin: float, tint: float) -> Array:
    """White balance in Kelvin + Tint, applied as channel gains in linear light.

    ``kelvin`` is the Temperature (~2000-50000 K); ``tint`` is green/magenta in
    -100..100. ``kelvin == WB_REFERENCE_K`` and ``tint == 0`` is a no-op (as-shot).
    """
    if kelvin == WB_REFERENCE_K and tint == 0.0:
        return rgb
    out: Array = np.maximum(rgb * _wb_gains(kelvin, tint), 0.0).astype(np.float32)
    return out


def solve_white_balance(pixel: Array) -> tuple[float, float]:
    """Kelvin + Tint that neutralise ``pixel`` (the eyedropper / WB selector).

    Searches the Kelvin range for the temperature whose gains best balance the
    red/blue ratio of the sampled (linear) pixel, then derives Tint from the green
    residual. Returns ``(kelvin, tint)`` to drive the Temp/Tint sliders.
    """
    r, g, b = (float(max(c, 1e-4)) for c in pixel[:3])
    target_ratio = b / r  # gain_r / gain_b needed to equalise red and blue
    best_k, best_err = WB_REFERENCE_K, float("inf")
    for step in range(60):
        kelvin = 2000.0 + step * (15000.0 - 2000.0) / 59.0
        gains = _wb_gains(kelvin, 0.0)
        err = abs((gains[0] / gains[2]) - target_ratio)
        if err < best_err:
            best_err, best_k = err, kelvin
    gains = _wb_gains(best_k, 0.0)
    # After the Kelvin balance, what green tweak makes green match the R/B average?
    balanced_g = g * gains[1]
    balanced_rb = 0.5 * (r * gains[0] + b * gains[2])
    ratio = balanced_g / max(balanced_rb, 1e-4)
    tint = float(np.clip((ratio - 1.0) * 200.0, -100.0, 100.0))
    return float(best_k), tint


def exposure_linear(rgb: Array, ev: float) -> Array:
    """Exposure in stops — a single linear multiply (``2**ev``), headroom kept."""
    if ev == 0.0:
        return rgb
    out: Array = np.maximum(rgb * (2.0**ev), 0.0).astype(np.float32)
    return out


def tone_linear(
    rgb: Array, highlights: float, shadows: float, whites: float, blacks: float
) -> Array:
    """Highlights / Shadows / Whites / Blacks as linear region gains.

    Region masks use a *perceptual* luminance position (sRGB-encoded luminance) so
    the controls target the tones a photographer expects, while the gains apply in
    linear light so recovery rolls off naturally.
    """
    if highlights == 0.0 and shadows == 0.0 and whites == 0.0 and blacks == 0.0:
        return rgb
    perceptual = linear_to_srgb(clip01(luminance(rgb)))[..., None]
    out = rgb
    if shadows != 0.0:
        mask = np.clip(1.0 - perceptual / 0.5, 0.0, 1.0) ** 2
        out = out * (1.0 + (shadows / 100.0) * 0.6 * mask)
    if highlights != 0.0:
        mask = np.clip((perceptual - 0.5) / 0.5, 0.0, 1.0) ** 2
        out = out * (1.0 + (highlights / 100.0) * 0.6 * mask)
    if blacks != 0.0:
        mask = np.clip(1.0 - perceptual / 0.25, 0.0, 1.0) ** 2
        out = out * (1.0 + (blacks / 100.0) * 0.5 * mask)
    if whites != 0.0:
        mask = np.clip((perceptual - 0.7) / 0.3, 0.0, 1.0) ** 2
        out = out * (1.0 + (whites / 100.0) * 0.5 * mask)
    clamped: Array = np.maximum(out, 0.0).astype(np.float32)
    return clamped


#: Highlight reconstruction engages above this linear value (near sensor clipping).
_RECON_LO, _RECON_HI = 0.80, 1.0


def reconstruct_highlights(rgb: Array, amount: float) -> Array:
    """Roll colour-clipped highlights toward neutral white (clipped-channel recovery).

    Where a channel clips but others do not, the highlight keeps a colour cast (a
    blown sky goes cyan, a bulb goes magenta). This pulls each channel toward the
    pixel's brightest channel in the highlight zone, in proportion to ``amount``
    (0..100), so blown areas resolve to clean white instead of a coloured smear.
    """
    if amount == 0.0:
        return rgb
    brightest = np.max(rgb, axis=-1, keepdims=True)
    weight = np.clip((brightest - _RECON_LO) / (_RECON_HI - _RECON_LO), 0.0, 1.0)
    strength = (amount / 100.0) * weight
    out: Array = (rgb + (brightest - rgb) * strength).astype(np.float32)
    return out


def _shadow_toe(x: Array) -> Array:
    """Deepen tones below middle grey for filmic shadow density (anchored at grey).

    The darkening ramps in smoothly (a smoothstep weight) from zero *at* the pivot
    to ``_TOE_STRENGTH`` toward black, so middle grey and everything above are
    untouched and the curve stays smooth (C1) through the pivot — no kink at the
    anchor and no shift in exposure.
    """
    t = np.clip((_TOE_PIVOT - x) / _TOE_PIVOT, 0.0, 1.0)
    weight = t * t * (3.0 - 2.0 * t)  # smoothstep: zero value *and* slope at pivot
    out: Array = (x * (1.0 - _TOE_STRENGTH * weight)).astype(np.float32)
    return out


def tonemap(rgb: Array) -> Array:
    """Map scene-linear light to display sRGB with a filmic toe + highlight shoulder.

    A shadow toe deepens tones below middle grey (density/contrast, anchored at
    grey so exposure holds), then a soft shoulder rolls highlights above the knee
    smoothly toward white instead of clipping hard. The sRGB transfer then encodes
    linear → display. Together these give a RAW the contrasty "developed" look
    professional RAW editors opens to, rather than a flat plain-gamma encode; the Contrast slider
    and the rest of the look stack on top downstream.
    """
    x = _shadow_toe(np.maximum(rgb, 0.0))
    # The exp shoulder only matters above the knee — evaluate it just for those
    # pixels (typically a small highlight fraction) instead of the whole frame.
    over_mask = x > _SHOULDER_KNEE
    if over_mask.any():
        headroom = 1.0 - _SHOULDER_KNEE
        over = x[over_mask] - _SHOULDER_KNEE
        x[over_mask] = _SHOULDER_KNEE + headroom * (1.0 - np.exp(-over / headroom))
    return linear_to_srgb(x)
