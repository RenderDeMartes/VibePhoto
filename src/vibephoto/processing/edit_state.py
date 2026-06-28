"""EditState — the non-destructive description of a photo's edits.

A flat, JSON-serialisable record of every develop parameter (defaults all mean
"no change", so a fresh ``EditState`` is a no-op identity edit). The renderer in
:mod:`vibephoto.processing.pipeline` turns this into pixels; the XMP importer in
:mod:`vibephoto.presets` produces one from a professional RAW editors preset. Keeping edits as data
(never baked into pixels) is what makes the editor non-destructive and lets the
same edit drive a fast preview and a full-resolution export identically.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any

#: The eight HSL / B&W-mix colour bands, in the conventional order.
HSL_BANDS: tuple[str, ...] = (
    "red",
    "orange",
    "yellow",
    "green",
    "aqua",
    "blue",
    "purple",
    "magenta",
)


def _bands() -> dict[str, float]:
    return dict.fromkeys(HSL_BANDS, 0.0)


@dataclass
class EditState:
    """All develop parameters for one photo. Defaults = identity (no edit)."""

    # Creative/camera base look applied beneath every adjustment (see
    # :mod:`vibephoto.processing.profiles`). "Neutral" = identity.
    profile: str = "Neutral"

    # White balance (relative to as-shot): -100..100. Used by the display/JPEG path.
    temp: float = 0.0
    tint: float = 0.0

    # RAW white balance (scene-linear front-end): absolute Temperature in Kelvin +
    # Tint. Default = the 6500 K reference, i.e. as-shot/identity.
    wb_kelvin: float = 6500.0
    wb_tint: float = 0.0

    # Basic tone
    exposure: float = 0.0  # EV, -5..+5
    contrast: float = 0.0  # -100..100
    highlights: float = 0.0
    shadows: float = 0.0
    whites: float = 0.0
    blacks: float = 0.0

    # RAW clipped-highlight reconstruction (scene-linear only): 0..100. Rolls
    # colour-clipped highlights toward neutral so blown areas resolve cleanly.
    highlight_recovery: float = 0.0

    # Presence
    texture: float = 0.0
    clarity: float = 0.0
    dehaze: float = 0.0
    vibrance: float = 0.0
    saturation: float = 0.0

    # Parametric tone curve regions: -100..100
    park_highlights: float = 0.0
    park_lights: float = 0.0
    park_darks: float = 0.0
    park_shadows: float = 0.0

    # Point tone curves: control points in 0..255, empty = linear/identity.
    curve_rgb: list[tuple[int, int]] = field(default_factory=list)
    curve_red: list[tuple[int, int]] = field(default_factory=list)
    curve_green: list[tuple[int, int]] = field(default_factory=list)
    curve_blue: list[tuple[int, int]] = field(default_factory=list)

    # HSL: per-band hue/sat/lum, each -100..100
    hsl_hue: dict[str, float] = field(default_factory=_bands)
    hsl_sat: dict[str, float] = field(default_factory=_bands)
    hsl_lum: dict[str, float] = field(default_factory=_bands)

    # Black & white
    grayscale: bool = False
    bw_mix: dict[str, float] = field(default_factory=_bands)

    # Color grading (3-way + global). Hue 0..360, sat/lum -100..100.
    grade_shadow_hue: float = 0.0
    grade_shadow_sat: float = 0.0
    grade_shadow_lum: float = 0.0
    grade_mid_hue: float = 0.0
    grade_mid_sat: float = 0.0
    grade_mid_lum: float = 0.0
    grade_highlight_hue: float = 0.0
    grade_highlight_sat: float = 0.0
    grade_highlight_lum: float = 0.0
    grade_global_hue: float = 0.0
    grade_global_sat: float = 0.0
    grade_blending: float = 50.0  # 0..100
    grade_balance: float = 0.0  # -100..100

    # Detail
    sharpen_amount: float = 0.0  # 0..150
    sharpen_radius: float = 1.0  # 0.5..3
    sharpen_detail: float = 25.0  # 0..100
    sharpen_masking: float = 0.0  # 0..100
    noise_luminance: float = 0.0  # 0..100
    noise_color: float = 0.0  # 0..100

    # Manual lens corrections (see :mod:`vibephoto.processing.lens`)
    lens_distortion: float = 0.0  # -100..100 (barrel/pincushion)
    lens_ca: float = 0.0  # -100..100 (chromatic aberration / defringe)
    lens_vignetting: float = 0.0  # -100..100 (corner brighten/darken)

    # Effects
    vignette_amount: float = 0.0  # -100..100
    vignette_midpoint: float = 50.0  # 0..100
    grain_amount: float = 0.0  # 0..100

    # -- serialisation ----------------------------------------------------- #

    def to_dict(self) -> dict[str, Any]:
        """A plain, JSON-ready dict (tuples become lists)."""
        out: dict[str, Any] = {}
        for f in fields(self):
            value = getattr(self, f.name)
            if f.name.startswith("curve_"):
                out[f.name] = [[int(x), int(y)] for x, y in value]
            elif isinstance(value, dict):
                out[f.name] = dict(value)
            else:
                out[f.name] = value
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EditState:
        """Build from a dict, ignoring unknown keys and filling missing defaults."""
        state = cls()
        known = {f.name for f in fields(cls)}
        for key, value in data.items():
            if key not in known:
                continue
            if key.startswith("curve_") and isinstance(value, list):
                setattr(state, key, [(int(p[0]), int(p[1])) for p in value])
            elif key in ("hsl_hue", "hsl_sat", "hsl_lum", "bw_mix") and isinstance(value, dict):
                merged = _bands()
                merged.update({k: float(v) for k, v in value.items() if k in HSL_BANDS})
                setattr(state, key, merged)
            elif key == "grayscale":
                setattr(state, key, bool(value))
            else:
                setattr(state, key, value)
        return state

    def is_identity(self) -> bool:
        """True when this edit changes nothing (every parameter at its default)."""
        return self.to_dict() == EditState().to_dict()

    def copy(self) -> EditState:
        return EditState.from_dict(self.to_dict())
