"""Manual lens corrections — distortion, vignetting, and chromatic aberration.

Profile-based *automatic* correction needs a lens-profile database; these are the
*manual* controls (like a pro editor's Lens » Manual tab), which are pure geometry
and need no external data. All operate on a display-space ``(H, W, 3)`` float image:

* **Distortion** — a radial remap that pulls in barrel / pushes out pincushion.
* **Vignetting** — a radial gain that brightens (or darkens) the corners to undo
  lens falloff (distinct from the creative Effects vignette).
* **Chromatic aberration** — a small opposed radial scale of the red and blue
  channels to re-converge lateral colour fringing.

The remap uses a vectorised bilinear sampler so it stays NumPy-only.
"""

from __future__ import annotations

import numpy as np

from vibephoto.processing.color import Array, clip01

try:  # OpenCV remap resamples all channels in one SIMD multithreaded pass.
    import cv2
except ImportError:  # pragma: no cover - exercised on installs without the cv extra
    cv2 = None  # type: ignore[assignment]


def _radial_grid(height: int, width: int) -> tuple[Array, Array, Array]:
    """Centre-origin coordinate grids ``(gx, gy)`` and radius ``r`` (1.0 at the
    short-edge half), all shaped ``(H, W)``."""
    ys = (np.arange(height, dtype=np.float32) - (height - 1) / 2.0)
    xs = (np.arange(width, dtype=np.float32) - (width - 1) / 2.0)
    gy, gx = np.meshgrid(ys, xs, indexing="ij")
    norm = max(1.0, min(height, width) / 2.0)
    r = np.sqrt(gx * gx + gy * gy) / norm
    return gx.astype(np.float32), gy.astype(np.float32), r.astype(np.float32)


def _sample(channel: Array, xs: Array, ys: Array) -> Array:
    """Bilinear-sample ``channel`` at float pixel coordinates ``(xs, ys)``."""
    height, width = channel.shape
    x0 = np.floor(xs).astype(np.int32)
    y0 = np.floor(ys).astype(np.int32)
    fx = (xs - x0).astype(np.float32)
    fy = (ys - y0).astype(np.float32)
    x0c = np.clip(x0, 0, width - 1)
    x1c = np.clip(x0 + 1, 0, width - 1)
    y0c = np.clip(y0, 0, height - 1)
    y1c = np.clip(y0 + 1, 0, height - 1)
    top = channel[y0c, x0c] * (1.0 - fx) + channel[y0c, x1c] * fx
    bot = channel[y1c, x0c] * (1.0 - fx) + channel[y1c, x1c] * fx
    out: Array = (top * (1.0 - fy) + bot * fy).astype(np.float32)
    return out


def _sample_rgb(rgb: Array, map_x: Array, map_y: Array) -> Array:
    """Bilinear-resample all three channels at the given source coordinates."""
    if cv2 is not None:
        remapped = cv2.remap(
            np.ascontiguousarray(rgb, dtype=np.float32),
            np.ascontiguousarray(map_x, dtype=np.float32),
            np.ascontiguousarray(map_y, dtype=np.float32),
            interpolation=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE,
        )
        return np.asarray(remapped, dtype=np.float32)
    out = np.empty_like(rgb)
    for c in range(rgb.shape[2]):
        out[..., c] = _sample(rgb[..., c], map_x, map_y)
    return out.astype(np.float32)


def _remap_radial(rgb: Array, scale_per_channel: tuple[float, float, float]) -> Array:
    """Resample each channel after scaling source radius by ``1 + s*r²`` per channel."""
    height, width = rgb.shape[0], rgb.shape[1]
    gx, gy, r = _radial_grid(height, width)
    r2 = r * r
    cx, cy = (width - 1) / 2.0, (height - 1) / 2.0
    out = np.empty_like(rgb)
    for c, s in enumerate(scale_per_channel):
        factor = 1.0 + s * r2
        channel = rgb[..., c]
        if cv2 is not None:
            remapped = cv2.remap(
                np.ascontiguousarray(channel, dtype=np.float32),
                np.ascontiguousarray(cx + gx * factor, dtype=np.float32),
                np.ascontiguousarray(cy + gy * factor, dtype=np.float32),
                interpolation=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_REPLICATE,
            )
            out[..., c] = remapped
        else:
            out[..., c] = _sample(channel, cx + gx * factor, cy + gy * factor)
    return out.astype(np.float32)


def _distortion_zoom(s2: float, s4: float, corner_r: float) -> float:
    """Destination pre-scale that keeps every distortion sample inside the frame.

    Correcting barrel distortion samples the source *outside* the frame at the
    edges, which smears the border pixels into streaks. Scaling the destination
    grid by ``z < 1`` (i.e. zooming in — cropping closer) keeps the far corner's
    sample exactly on the original corner: solve ``z·f(corner_r·z) = 1`` by fixed-
    point iteration (``f`` is the radial factor; converges fast for ``s ≥ 0``).
    """
    if s2 <= 0.0 and s4 <= 0.0:
        return 1.0
    z = 1.0
    for _ in range(40):
        rz2 = (corner_r * z) ** 2
        z = 1.0 / (1.0 + s2 * rz2 + s4 * rz2 * rz2)
    return z


def _remap_distort(rgb: Array, s2: float, s4: float) -> Array:
    """Resample with a 2nd + 4th order radial factor (``1 + s2·r² + s4·r⁴``).

    The 4th-order term lets a strong setting pull a fisheye's hard-bent edges back
    to straight, which a pure quadratic cannot. For positive (barrel) correction
    the frame is automatically zoomed in just enough that no sample falls outside
    the source, so the result has clean edges instead of smeared borders.
    """
    height, width = rgb.shape[0], rgb.shape[1]
    gx, gy, r = _radial_grid(height, width)
    norm = max(1.0, min(height, width) / 2.0)
    corner_r = float(np.hypot((width - 1) / 2.0, (height - 1) / 2.0) / norm)
    zoom = _distortion_zoom(s2, s4, corner_r)
    r2 = (r * zoom) ** 2
    factor = zoom * (1.0 + s2 * r2 + s4 * r2 * r2)
    cx, cy = (width - 1) / 2.0, (height - 1) / 2.0
    return _sample_rgb(rgb, cx + gx * factor, cy + gy * factor)


def correct_distortion(rgb: Array, amount: float) -> Array:
    """Correct barrel (``amount`` > 0) / pincushion (< 0) distortion (-100..100).

    Strong positive values defish: the 4th-order term straightens the extreme
    edge curvature of a fisheye / action-cam lens. The corrected frame is scaled
    to fill (cropping in slightly), so no stretched border pixels remain.
    """
    if amount == 0.0:
        return rgb
    k = amount / 100.0
    return _remap_distort(rgb, k * 0.30, k * 0.25)


def scale_image(rgb: Array, percent: float) -> Array:
    """Zoom about the centre: ``percent`` > 100 crops closer (100 = no change).

    The manual companion to the automatic distortion zoom — scale in a little
    further to hide any remaining corner artefacts. Values below 100 are clamped
    (zooming out would invent border pixels).
    """
    if percent <= 100.0:
        return rgb
    height, width = rgb.shape[0], rgb.shape[1]
    gx, gy, _r = _radial_grid(height, width)
    inv = 100.0 / percent
    cx, cy = (width - 1) / 2.0, (height - 1) / 2.0
    return _sample_rgb(rgb, cx + gx * inv, cy + gy * inv)


def correct_chromatic_aberration(rgb: Array, amount: float) -> Array:
    """Re-converge lateral CA: scale red out and blue in (or vice versa), -100..100."""
    if amount == 0.0:
        return rgb
    k = amount / 100.0 * 0.04
    return _remap_radial(rgb, (k, 0.0, -k))


def correct_vignetting(rgb: Array, amount: float) -> Array:
    """Radially brighten (``amount`` > 0) or darken (< 0) the corners (-100..100)."""
    if amount == 0.0:
        return rgb
    _gx, _gy, r = _radial_grid(rgb.shape[0], rgb.shape[1])
    gain = 1.0 + (amount / 100.0) * 0.8 * np.clip(r, 0.0, 1.4) ** 2
    out: Array = clip01(rgb * gain[..., None])
    return out


#: Sentinel meaning "leave the manual sliders as-is" (the Manual profile).
MANUAL_PROFILE = "Manual (use sliders)"

#: Built-in lens-correction profiles, grouped (group, name, distortion, ca, vignetting).
#: Generic profiles are by lens *type*; the Canon/Sony entries are tuned approximations
#: for specific popular lenses (no per-camera measurement database — pick the closest
#: match, then fine-tune with the manual sliders if needed).
LENS_PROFILE_GROUPS: tuple[tuple[str, tuple[tuple[str, float, float, float], ...]], ...] = (
    ("Generic", (
        ("None", 0.0, 0.0, 0.0),
        ("Fisheye — Full (180°)", 100.0, 10.0, 38.0),
        ("Fisheye — Diagonal", 78.0, 8.0, 28.0),
        ("Action cam (wide)", 88.0, 12.0, 42.0),
        ("Ultra-wide", 46.0, 6.0, 30.0),
        ("Wide-angle", 26.0, 4.0, 20.0),
    )),
    ("Canon", (
        ("Canon EF 8-15mm f/4L Fisheye", 92.0, 9.0, 34.0),
        ("Canon EF-S 10-18mm", 40.0, 5.0, 26.0),
        ("Canon EF 11-24mm f/4L", 30.0, 5.0, 24.0),
        ("Canon EF 16-35mm f/4L", 22.0, 4.0, 22.0),
        ("Canon RF 15-35mm f/2.8L", 24.0, 4.0, 20.0),
    )),
    ("Sony", (
        ("Sony E 10-18mm f/4", 38.0, 5.0, 25.0),
        ("Sony FE 12-24mm f/4 G", 30.0, 5.0, 24.0),
        ("Sony FE 14mm f/1.8 GM", 26.0, 4.0, 22.0),
        ("Sony FE 16-35mm f/2.8 GM", 22.0, 4.0, 20.0),
    )),
)

#: Flat ``name -> (distortion, ca, vignetting)`` for the engine + detection.
LENS_PROFILES: dict[str, tuple[float, float, float]] = {
    name: (d, ca, vig)
    for _group, lenses in LENS_PROFILE_GROUPS
    for (name, d, ca, vig) in lenses
}

LENS_PROFILE_NAMES: tuple[str, ...] = tuple(LENS_PROFILES)
#: Fallback when no lens metadata is available (the user's common case is fisheye).
AUTO_LENS_PROFILE = "Fisheye — Full (180°)"

#: Substrings (in a lens-model EXIF string) → the exact built-in profile to apply.
_LENS_MODEL_MATCHES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("8-15", "ef8-15", "ef 8-15"), "Canon EF 8-15mm f/4L Fisheye"),
    (("10-18", "ef-s 10-18", "e 10-18"), "Canon EF-S 10-18mm"),
    (("11-24",), "Canon EF 11-24mm f/4L"),
    (("16-35",), "Canon EF 16-35mm f/4L"),
    (("15-35",), "Canon RF 15-35mm f/2.8L"),
    (("12-24",), "Sony FE 12-24mm f/4 G"),
    (("fe 14mm", "14mm f/1.8"), "Sony FE 14mm f/1.8 GM"),
)


def _match_named_profile(lens: str | None, camera_model: str | None) -> str | None:
    """An exact built-in lens profile whose model substring appears in the EXIF."""
    text = " ".join(p for p in (lens, camera_model) if p).lower()
    if not text:
        return None
    is_sony = "sony" in text or "ilce" in text  # Sony bodies report 'ILCE-...'
    for needles, profile in _LENS_MODEL_MATCHES:
        if any(n in text for n in needles):
            # The 16-35 / shared focal ranges exist for both makers — prefer Sony's if a
            # Sony body is detected and a Sony equivalent exists.
            if is_sony and "16-35" in profile and "Sony FE 16-35mm f/2.8 GM" in LENS_PROFILES:
                return "Sony FE 16-35mm f/2.8 GM"
            return profile
    return None


def _to_focal(value: object) -> float | None:
    """Coerce an EXIF focal length (float / IFDRational / str / None) to mm."""
    if value is None:
        return None
    try:
        focal = float(value)  # type: ignore[arg-type]  # numbers + PIL IFDRational
    except (TypeError, ValueError):
        try:  # strings like "8 mm" / "8.0mm"
            focal = float(str(value).lower().replace("mm", "").strip())
        except (TypeError, ValueError):
            return None
    return focal if focal > 0 else None


def detect_lens_profile(
    lens: str | None, focal_length: object, camera_model: str | None = None
) -> str | None:
    """Pick a lens-correction profile from EXIF lens / focal length / camera.

    Returns a :data:`LENS_PROFILES` key, ``"None"`` for a normal lens that needs no
    correction, or ``None`` when there is no metadata to decide from (so the caller
    can fall back to its own default). A pure, testable heuristic — no lens database;
    tolerant of messy EXIF (missing or oddly-typed values).
    """
    named = _match_named_profile(lens, camera_model)
    if named is not None:
        return named  # exact lens match (e.g. Canon EF 8-15mm) wins over the generic guess
    text = " ".join(part for part in (lens, camera_model) if part).strip().lower()
    focal = _to_focal(focal_length)
    if not text and focal is None:
        return None  # nothing to go on
    if any(word in text for word in ("fisheye", "fish-eye", "fish eye", "peleng", "circular")):
        return "Fisheye — Diagonal" if "diagonal" in text else "Fisheye — Full (180°)"
    if any(word in text for word in ("gopro", "insta360", "dji", "osmo", "action", "pocket")):
        return "Action cam (wide)"
    if focal is not None:
        if focal <= 9.0:
            return "Ultra-wide"
        if focal <= 16.0:
            return "Wide-angle"
        return "None"  # standard / tele lens — no geometric correction
    return None  # had a lens name but no focal length and no match

