"""Color-science primitives for the processing engine.

Pure NumPy helpers shared by the adjustment operators: the sRGB transfer
functions (so exposure/white-balance math can happen in linear light), a fast
separable blur (local-contrast, sharpening, noise reduction), vectorised HSV
conversion (HSL adjustments, color grading), Rec.709 luminance, and tone-curve
LUT construction.

Images are ``float32`` arrays shaped ``(H, W, 3)`` with values nominally in
``[0, 1]``. The display-space operators work in *gamma-encoded* sRGB (perceptually
uniform, where professional sliders feel right). RAW develops in **scene-linear**
light first (see :mod:`vibephoto.processing.scene_linear`): white balance, exposure,
and tone run in linear, then a base tone-map converts to display sRGB for the rest of
the pipeline. Full ICC colour management (wide-gamut working space, output profiles)
still lands later.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

try:  # OpenCV: SIMD + multithreaded kernels for the hot per-pixel work.
    import cv2
except ImportError:  # pragma: no cover - exercised on installs without the cv extra
    cv2 = None  # type: ignore[assignment]

Array = NDArray[np.float32]

#: Rec.709 luminance weights (R, G, B).
_LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)

#: Resolution of the sRGB transfer LUTs. 16-bit quantisation keeps the round-trip
#: error < 5e-5 — far below one 8-bit display step — while replacing the per-pixel
#: ``**2.4`` transcendental with a single table gather (~10x faster).
_TRANSFER_LUT_SIZE = 65536
_srgb_to_linear_lut: Array | None = None
_linear_to_srgb_lut: Array | None = None


def clip01(arr: Array) -> Array:
    return np.clip(arr, 0.0, 1.0).astype(np.float32)


def _transfer_luts() -> tuple[Array, Array]:
    """Lazily build the sRGB↔linear lookup tables (a few hundred KB, built once)."""
    global _srgb_to_linear_lut, _linear_to_srgb_lut
    if _srgb_to_linear_lut is None or _linear_to_srgb_lut is None:
        ramp = np.linspace(0.0, 1.0, _TRANSFER_LUT_SIZE, dtype=np.float64)
        to_linear = np.where(ramp <= 0.04045, ramp / 12.92, ((ramp + 0.055) / 1.055) ** 2.4)
        to_srgb = np.where(
            ramp <= 0.0031308, ramp * 12.92, 1.055 * (ramp ** (1.0 / 2.4)) - 0.055
        )
        _srgb_to_linear_lut = to_linear.astype(np.float32)
        _linear_to_srgb_lut = to_srgb.astype(np.float32)
    return _srgb_to_linear_lut, _linear_to_srgb_lut


def srgb_to_linear(arr: Array) -> Array:
    """Inverse sRGB transfer (gamma → linear light)."""
    # Nearest-entry gather: the transfer's slope is ≤ 2.4, so 16-bit quantisation
    # keeps the error below 2e-5.
    lut = _transfer_luts()[0]
    idx = (np.clip(arr, 0.0, 1.0) * (_TRANSFER_LUT_SIZE - 1) + 0.5).astype(np.uint16)
    out: Array = lut[idx]
    return out


def linear_to_srgb(arr: Array) -> Array:
    """Forward sRGB transfer (linear light → gamma)."""
    # Linear interpolation between entries: near black the transfer's slope is
    # 12.92, so a nearest gather would quantise visibly; the lerp keeps the error
    # below 1e-6 while still avoiding the per-pixel ``** (1/2.4)``.
    lut = _transfer_luts()[1]
    pos = np.clip(arr, 0.0, 1.0).astype(np.float32) * np.float32(_TRANSFER_LUT_SIZE - 1)
    idx = np.minimum(pos.astype(np.uint16), _TRANSFER_LUT_SIZE - 2)
    frac = pos - idx
    out: Array = (lut[idx] * (1.0 - frac) + lut[idx + 1] * frac).astype(np.float32)
    return out


def luminance(rgb: Array) -> Array:
    """Per-pixel Rec.709 luminance, shape ``(H, W)``."""
    return (rgb @ _LUMA).astype(np.float32)


def _box_blur_axis0(arr: Array, radius: int) -> Array:
    """Box blur along axis 0 via a cumulative-sum sliding window (O(n))."""
    pad = [(radius, radius)] + [(0, 0)] * (arr.ndim - 1)
    padded = np.pad(arr, pad, mode="edge")
    cumsum = np.cumsum(padded, axis=0, dtype=np.float32)
    zero = np.zeros((1, *cumsum.shape[1:]), dtype=np.float32)
    cumsum = np.concatenate([zero, cumsum], axis=0)
    width = 2 * radius + 1
    n = arr.shape[0]
    return ((cumsum[width : width + n] - cumsum[:n]) / width).astype(np.float32)


def box_blur(arr: Array, radius: int) -> Array:
    if radius < 1:
        return arr.astype(np.float32)
    out = _box_blur_axis0(arr, radius)
    out = _box_blur_axis0(np.swapaxes(out, 0, 1), radius)
    return np.ascontiguousarray(np.swapaxes(out, 0, 1)).astype(np.float32)


def gaussian_blur(arr: Array, sigma: float) -> Array:
    """Gaussian blur. OpenCV kernel when available, else three box blurs (central-limit)."""
    if sigma <= 0:
        return arr.astype(np.float32)
    if cv2 is not None:
        src = np.ascontiguousarray(arr, dtype=np.float32)
        blurred = cv2.GaussianBlur(
            src, (0, 0), sigmaX=float(sigma), borderType=cv2.BORDER_REPLICATE
        )
        return np.asarray(blurred, dtype=np.float32)
    radius = max(1, round(sigma))
    fallback = arr.astype(np.float32)
    for _ in range(3):
        fallback = box_blur(fallback, radius)
    return fallback


def rgb_to_hsv(rgb: Array) -> Array:
    """Vectorised RGB→HSV. Input/output ``(H, W, 3)``; H,S,V all in ``[0, 1]``."""
    if cv2 is not None and rgb.ndim == 3 and rgb.shape[-1] == 3:
        src = np.ascontiguousarray(np.clip(rgb, 0.0, 1.0), dtype=np.float32)
        hsv = np.asarray(cv2.cvtColor(src, cv2.COLOR_RGB2HSV), dtype=np.float32)
        hsv[..., 0] *= np.float32(1.0 / 360.0)  # cv2 float HSV uses H in [0, 360)
        return hsv
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    maxc = np.max(rgb, axis=-1)
    minc = np.min(rgb, axis=-1)
    delta = maxc - minc
    value = maxc
    sat = np.where(maxc > 1e-8, delta / np.maximum(maxc, 1e-8), 0.0)

    safe = np.where(delta > 1e-8, delta, 1.0)
    rc = (maxc - r) / safe
    gc = (maxc - g) / safe
    bc = (maxc - b) / safe
    hue = np.zeros_like(maxc)
    hue = np.where(maxc == r, bc - gc, hue)
    hue = np.where(maxc == g, 2.0 + rc - bc, hue)
    hue = np.where(maxc == b, 4.0 + gc - rc, hue)
    hue = (hue / 6.0) % 1.0
    hue = np.where(delta <= 1e-8, 0.0, hue)
    out: Array = np.stack([hue, sat, value], axis=-1).astype(np.float32)
    return out


def hsv_to_rgb(hsv: Array) -> Array:
    """Vectorised HSV→RGB. Input/output ``(H, W, 3)`` in ``[0, 1]``."""
    if cv2 is not None and hsv.ndim == 3 and hsv.shape[-1] == 3:
        src = np.array(hsv, dtype=np.float32, copy=True, order="C")
        src[..., 0] = (src[..., 0] % 1.0) * np.float32(360.0)
        return np.asarray(cv2.cvtColor(src, cv2.COLOR_HSV2RGB), dtype=np.float32)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    i = np.floor(h * 6.0)
    f = h * 6.0 - i
    i = i.astype(np.int32) % 6
    p = v * (1.0 - s)
    q = v * (1.0 - f * s)
    t = v * (1.0 - (1.0 - f) * s)

    r = np.select([i == 0, i == 1, i == 2, i == 3, i == 4, i == 5], [v, q, p, p, t, v])
    g = np.select([i == 0, i == 1, i == 2, i == 3, i == 4, i == 5], [t, v, v, q, p, p])
    b = np.select([i == 0, i == 1, i == 2, i == 3, i == 4, i == 5], [p, p, t, v, v, q])
    out: Array = np.stack([r, g, b], axis=-1).astype(np.float32)
    return out


def lut_from_points(points: list[tuple[float, float]]) -> Array:
    """Build a 256-entry LUT in ``[0, 1]`` from control points given in 0..255.

    Points are sorted and linearly interpolated; an empty/identity set yields the
    identity ramp. Monotonic linear interpolation keeps tone curves well-behaved.
    """
    ramp = np.arange(256, dtype=np.float32)
    if not points:
        return (ramp / 255.0).astype(np.float32)
    pts = sorted(points)
    xs = np.array([p[0] for p in pts], dtype=np.float32)
    ys = np.array([p[1] for p in pts], dtype=np.float32)
    lut = np.interp(ramp, xs, ys).astype(np.float32) / 255.0
    clamped: Array = np.clip(lut, 0.0, 1.0).astype(np.float32)
    return clamped


def apply_lut(channel: Array, lut: Array) -> Array:
    """Apply a 256-entry ``[0, 1]`` LUT to a ``[0, 1]`` channel."""
    idx = np.clip(channel * 255.0, 0, 255).astype(np.int32)
    mapped: Array = lut[idx].astype(np.float32)
    return mapped
