"""Image writers, resizing, and watermarking for the export pipeline.

Pure functions over ``(H, W, 3)`` uint8 arrays + Pillow, so they are testable
headless and shared by every export path. Format coverage is JPG/PNG/TIFF for
now; DNG/HDR writers attach here later without touching callers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageDraw, ImageFont

from vibephoto.export.color_profiles import srgb_icc_bytes

#: An 8-bit (uint8) or 16-bit (uint16) RGB raster — the two export bit depths.
PixelArray = NDArray[np.unsignedinteger[Any]]


def resize_to_long_edge(rgb: NDArray[np.uint8], long_edge: int | None) -> NDArray[np.uint8]:
    """Downscale so the longest side is ``long_edge`` (None / fits already = unchanged)."""
    if long_edge is None:
        return rgb
    height, width = rgb.shape[0], rgb.shape[1]
    if max(height, width) <= long_edge:
        return rgb
    image = Image.fromarray(rgb)
    image.thumbnail((long_edge, long_edge), Image.Resampling.LANCZOS)
    return np.asarray(image.convert("RGB"), dtype=np.uint8)


def apply_watermark(rgb: PixelArray, text: str) -> PixelArray:
    """Draw a semi-transparent white text watermark in the bottom-right corner.

    Depth-agnostic: composites in float against the array's own range, so an 8-bit
    (uint8) or 16-bit (uint16) export keeps its bit depth through the watermark.
    """
    if not text:
        return rgb
    height, width = int(rgb.shape[0]), int(rgb.shape[1])
    maxval = 65535.0 if rgb.dtype == np.uint16 else 255.0
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    size = max(14, width // 40)
    try:
        font: ImageFont.ImageFont | ImageFont.FreeTypeFont = ImageFont.truetype("arial.ttf", size)
    except OSError:
        font = ImageFont.load_default()
    box = draw.textbbox((0, 0), text, font=font)
    tw, th = box[2] - box[0], box[3] - box[1]
    margin = max(8, width // 100)
    pos = (width - tw - margin, height - th - margin * 2)
    draw.text(pos, text, font=font, fill=180)  # 180/255 ≈ 0.7 alpha
    alpha = (np.asarray(mask, dtype=np.float32) / 255.0)[..., None]
    blended = rgb.astype(np.float32) * (1.0 - alpha) + maxval * alpha
    out: PixelArray = blended.astype(rgb.dtype)
    return out


def write_image(rgb: PixelArray, dest: Path, fmt: str, quality: int) -> None:
    """Write an RGB array to ``dest`` in the given format.

    Accepts an 8-bit (uint8) or 16-bit (uint16) RGB array; 16-bit is written as a
    16-bit TIFF (the only format here that holds 16-bit RGB), everything else as
    8-bit. Every export embeds the sRGB ICC profile (the pipeline's working space)
    so the file declares its colours instead of leaving them to the viewer's guess.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    kind = fmt.lower()
    icc = srgb_icc_bytes()

    if rgb.dtype == np.uint16:
        if kind not in ("tif", "tiff"):
            raise ValueError(f"16-bit export is only supported for TIFF, not {fmt!r}")
        _write_tiff16(rgb, dest, icc)
        return

    image = Image.fromarray(rgb).convert("RGB")
    extra = {"icc_profile": icc} if icc else {}
    if kind in ("jpg", "jpeg"):
        image.save(dest, "JPEG", quality=int(quality), subsampling=0, optimize=True, **extra)
    elif kind == "png":
        image.save(dest, "PNG", **extra)
    elif kind in ("tif", "tiff"):
        image.save(dest, "TIFF", **extra)
    else:
        raise ValueError(f"Unsupported export format: {fmt!r}")


def _write_tiff16(rgb: NDArray[np.uint16], dest: Path, icc: bytes | None) -> None:
    """Write a 16-bit RGB TIFF (Pillow has no 16-bit RGB TIFF writer; tifffile does).

    The sRGB profile is embedded via the standard ICCProfile tag (34675) so the
    16-bit file is colour-managed exactly like the 8-bit path.
    """
    import tifffile

    # ICCProfile tag: (code, dtype=BYTE/1, count, value, writeonce).
    extratags = [(34675, 1, len(icc), icc, True)] if icc else []
    tifffile.imwrite(
        str(dest),
        np.ascontiguousarray(rgb),
        photometric="rgb",
        compression="adobe_deflate",
        extratags=extratags,
    )
