"""Colorspace-preserving image downscale.

Used for preview/proxy sizing. Crucially this resizes in **float**, so a
scene-linear buffer (RAW) keeps its linear values and headroom — a uint8 round
trip would quantise it to 256 levels and defeat the whole point of decoding RAW.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from vibephoto.processing.image_buffer import ImageBuffer


def downscale_buffer(buffer: ImageBuffer, long_edge: int) -> ImageBuffer:
    """Return ``buffer`` scaled so its longest side is ``long_edge`` (0 = no change).

    Resizes each channel as a 32-bit float image (PIL ``F`` mode), preserving the
    buffer's colorspace tag and full numeric range.
    """
    height, width = buffer.height, buffer.width
    if long_edge <= 0 or max(height, width) <= long_edge:
        return buffer
    scale = long_edge / max(height, width)
    new_w = max(1, round(width * scale))
    new_h = max(1, round(height * scale))
    data = buffer.data
    channels = [
        np.asarray(
            Image.fromarray(data[..., c], mode="F").resize(
                (new_w, new_h), Image.Resampling.LANCZOS
            ),
            dtype=np.float32,
        )
        for c in range(3)
    ]
    resized = np.ascontiguousarray(np.stack(channels, axis=-1))
    return ImageBuffer(resized, buffer.colorspace)
