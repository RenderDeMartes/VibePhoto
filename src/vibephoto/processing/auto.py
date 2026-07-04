"""Automatic adjustments — one-click "Auto Edit" and "Auto HDR".

Both analyse the actual pixels of a photo's base buffer and return an
:class:`EditState`, so the result adapts to each image. ``auto_tone`` is a
professional auto: centre the exposure, recover clipped highlights, lift
crushed shadows, set sensible white/black points, add a little contrast/vibrance.
``auto_hdr`` builds on that with a single-image HDR tone-map look (strong
shadow/highlight balancing + clarity); true multi-bracket HDR merge is the
separate Phase-6 engine.
"""

from __future__ import annotations

import numpy as np

from vibephoto.processing.color import luminance
from vibephoto.processing.edit_state import EditState
from vibephoto.processing.image_buffer import ImageBuffer


def _srgb_value_to_linear(value: float) -> float:
    """Scalar inverse sRGB transfer (the analysed buffer is display-referred)."""
    if value <= 0.04045:
        return value / 12.92
    return float(((value + 0.055) / 1.055) ** 2.4)


def auto_tone(buffer: ImageBuffer) -> EditState:
    """Compute an auto-tone :class:`EditState` from an image's luminance stats."""
    lum = luminance(buffer.data)
    lo, q25, mid, q75, hi = (
        float(x) for x in np.percentile(lum, [1.0, 25.0, 50.0, 75.0, 99.0])
    )
    state = EditState()

    # Exposure: bring the median toward middle grey. The Exposure control is a
    # *linear-light* multiply (2**ev), so the stops must be computed from linear
    # luminance — a gamma-space ratio badly underestimates the lift a dark photo
    # needs (the old ±1.5 EV gamma version left night/dusk shots dark).
    linear_mid = _srgb_value_to_linear(mid)
    if linear_mid > 1e-5:
        state.exposure = float(np.clip(np.log2(0.18 / linear_mid), -2.5, 2.5))

    # Recover blown highlights / lift crushed shadows. The shadow lift also keys
    # off the lower quartile, so a broadly dark image gets help, not just one
    # with a crushed black point.
    if hi > 0.95:
        state.highlights = -float(np.clip((hi - 0.95) / 0.05 * 60.0, 0.0, 60.0))
    shadow_need = max((0.06 - lo) / 0.06, (0.20 - q25) / 0.20, 0.0)
    if shadow_need > 0.0:
        state.shadows = float(np.clip(shadow_need * 50.0, 0.0, 50.0))

    # White/black points: nudge toward gentle clipping for a fuller histogram.
    state.whites = float(np.clip((0.95 - hi) * 300.0, -20.0, 40.0))
    state.blacks = -float(np.clip((lo - 0.03) * 300.0, 0.0, 30.0))

    # A little contrast when the image is flat, plus a touch of vibrance.
    if (q75 - q25) < 0.25:
        state.contrast = float(np.clip((0.25 - (q75 - q25)) * 120.0, 0.0, 25.0))
    state.vibrance = 8.0
    return state


def auto_hdr(buffer: ImageBuffer) -> EditState:
    """A single-image HDR tone-map look, exposure-matched to the photo."""
    state = auto_tone(buffer)
    state.highlights = min(state.highlights, -70.0)
    state.shadows = max(state.shadows, 60.0)
    state.whites = -10.0
    state.blacks = 12.0
    state.clarity = 28.0
    state.dehaze = 12.0
    state.vibrance = max(state.vibrance, 18.0)
    state.contrast = state.contrast + 8.0
    return state
