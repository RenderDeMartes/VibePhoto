"""Creative / camera profiles — selectable base *looks*.

A profile is the starting rendering applied beneath the user's adjustments: a small
fixed combination of contrast, saturation, warmth, a matte fade, and (for the
monochrome look) desaturation. The default profile ``"Neutral"`` is an identity, so
a fresh edit is unchanged and a RAW still opens to the plain filmic base tone-map;
picking another profile shifts the whole look while the sliders keep working on top.

Profiles run in display space (after the base tone-map), as a single pipeline stage.
All transforms are pure NumPy so the look is reproducible on preview and export.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from vibephoto.processing.color import Array, clip01, hsv_to_rgb, luminance, rgb_to_hsv


@dataclass(frozen=True)
class Profile:
    """A base look. All amounts are gentle; ``Neutral`` (all zero) is identity."""

    contrast: float = 0.0  # -1..1 around mid-grey
    saturation: float = 0.0  # -1..1 (relative)
    warmth: float = 0.0  # -1..1 (warm > 0 / cool < 0)
    fade: float = 0.0  # 0..1 matte black lift
    monochrome: bool = False

    @property
    def is_identity(self) -> bool:
        return not (
            self.contrast or self.saturation or self.warmth or self.fade or self.monochrome
        )


#: The built-in profiles, in menu order. Names are generic by design.
PROFILES: dict[str, Profile] = {
    "Neutral": Profile(),
    "Standard": Profile(contrast=0.12, saturation=0.06),
    "Vivid": Profile(contrast=0.20, saturation=0.28),
    "Portrait": Profile(contrast=0.08, saturation=-0.04, warmth=0.05),
    "Landscape": Profile(contrast=0.18, saturation=0.20),
    "Flat": Profile(contrast=-0.18),
    "Matte": Profile(contrast=0.04, fade=0.10),
    "Warm Film": Profile(contrast=0.06, saturation=0.10, warmth=0.18, fade=0.06),
    "Cool Film": Profile(contrast=0.06, saturation=0.04, warmth=-0.16, fade=0.05),
    "Monochrome": Profile(contrast=0.14, monochrome=True),
}

PROFILE_NAMES: tuple[str, ...] = tuple(PROFILES)
DEFAULT_PROFILE = "Neutral"


def _contrast(rgb: Array, amount: float) -> Array:
    # Smooth S-curve around mid-grey; ``amount`` scales its strength.
    x = clip01(rgb)
    curved = np.asarray(
        x + amount * (x - 0.5) * (1.0 - np.abs(2.0 * x - 1.0)), dtype=np.float32
    )
    out: Array = clip01(curved)
    return out


def _saturate(rgb: Array, amount: float) -> Array:
    hsv = rgb_to_hsv(clip01(rgb))
    hsv[..., 1] = np.clip(hsv[..., 1] * (1.0 + amount), 0.0, 1.0)
    return hsv_to_rgb(hsv)


def _warm(rgb: Array, amount: float) -> Array:
    gain = np.array([1.0 + 0.18 * amount, 1.0, 1.0 - 0.18 * amount], dtype=np.float32)
    out: Array = clip01(rgb * gain)
    return out


def _fade(rgb: Array, amount: float) -> Array:
    # Lift the black point for a matte look (shadows never reach 0).
    lift = 0.12 * amount
    out: Array = clip01(lift + (1.0 - lift) * rgb)
    return out


def _monochrome(rgb: Array) -> Array:
    grey = luminance(clip01(rgb))[..., None]
    out: Array = np.repeat(grey, 3, axis=-1).astype(np.float32)
    return out


def apply_profile(rgb: Array, name: str) -> Array:
    """Apply the named profile's base look (``Neutral`` / unknown = unchanged)."""
    profile = PROFILES.get(name)
    if profile is None or profile.is_identity:
        return rgb
    out = rgb
    if profile.monochrome:
        out = _monochrome(out)
    if profile.warmth:
        out = _warm(out, profile.warmth)
    if profile.saturation:
        out = _saturate(out, profile.saturation)
    if profile.contrast:
        out = _contrast(out, profile.contrast)
    if profile.fade:
        out = _fade(out, profile.fade)
    return out.astype(np.float32)
