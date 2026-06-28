"""Export presets — named output recipes (format, size, quality, watermark).

Mirrors familiar export presets and the real-estate workflow targets from the
PRD (Web / Instagram / MLS / Full Resolution). An :class:`ExportPreset` is plain
data so the UI and the headless batch path use the exact same recipe.
"""

from __future__ import annotations

from dataclasses import dataclass

_EXT = {"jpg": "jpg", "jpeg": "jpg", "png": "png", "tiff": "tif", "tif": "tif"}


@dataclass(frozen=True)
class ExportPreset:
    """A named output recipe."""

    name: str
    fmt: str = "jpg"  # jpg | png | tiff
    quality: int = 90  # JPEG quality (1..100)
    long_edge: int | None = None  # resize longest side; None = full resolution
    watermark: str = ""  # text watermark, empty = none
    bit_depth: int = 8  # 8 or 16; 16 needs TIFF (JPEG/PNG export 8-bit RGB only)

    @property
    def extension(self) -> str:
        return _EXT.get(self.fmt.lower(), "jpg")

    @property
    def effective_bit_depth(self) -> int:
        """16 only when the format can hold 16-bit RGB (TIFF); else 8-bit.

        JPEG is 8-bit by spec; Pillow has no 16-bit RGB PNG writer — so TIFF is the
        16-bit handoff format the industry uses for high-bit-depth delivery.
        """
        if self.bit_depth >= 16 and self.fmt.lower() in ("tif", "tiff"):
            return 16
        return 8


#: Built-in export presets covering web, social, MLS, and full-res delivery.
BUILTIN_EXPORT_PRESETS: tuple[ExportPreset, ...] = (
    ExportPreset("Full Resolution JPEG", "jpg", 95, None),
    ExportPreset("Web (2048px)", "jpg", 85, 2048),
    ExportPreset("Instagram (1080px)", "jpg", 90, 1080),
    ExportPreset("MLS Real Estate (1920px)", "jpg", 88, 1920),
    ExportPreset("TIFF 16-bit (Full)", "tiff", 100, None, bit_depth=16),
    ExportPreset("PNG (Full)", "png", 100, None),
)
