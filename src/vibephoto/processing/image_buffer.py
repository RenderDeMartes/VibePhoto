"""ImageBuffer — the currency passed between pipeline stages.

A thin wrapper over a ``float32`` ``(H, W, 3)`` array in ``[0, 1]`` plus its
colour space. Conversions to/from 8-bit live here so the operators stay pure
float math and the UI/export layers have one obvious place to encode pixels.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from vibephoto.processing.color import Array, clip01


@dataclass(frozen=True, slots=True)
class ImageBuffer:
    """Immutable handle to a float RGB raster (stages return new buffers)."""

    data: Array
    colorspace: str = "srgb"

    @property
    def height(self) -> int:
        return int(self.data.shape[0])

    @property
    def width(self) -> int:
        return int(self.data.shape[1])

    @classmethod
    def from_uint8(cls, arr: NDArray[np.uint8], colorspace: str = "srgb") -> ImageBuffer:
        """Wrap an 8-bit RGB array, scaling to ``[0, 1]`` float32."""
        data = (arr.astype(np.float32) / 255.0)[..., :3]
        return cls(np.ascontiguousarray(data), colorspace)

    @classmethod
    def from_uint16(cls, arr: NDArray[np.uint16], colorspace: str = "srgb") -> ImageBuffer:
        """Wrap a 16-bit RGB array (e.g. a LibRaw demosaic), scaling to ``[0, 1]`` float32.

        Keeping the float buffer fed from 16-bit RAW data preserves the tonal
        headroom the 8-bit camera JPEG threw away, so tone edits have real range.
        """
        data = (arr.astype(np.float32) / 65535.0)[..., :3]
        return cls(np.ascontiguousarray(data), colorspace)

    def to_uint8(self) -> NDArray[np.uint8]:
        """Clip to ``[0, 1]`` and encode as 8-bit RGB for display/export."""
        return (clip01(self.data) * 255.0 + 0.5).astype(np.uint8)

    def to_uint16(self) -> NDArray[np.uint16]:
        """Clip to ``[0, 1]`` and encode as 16-bit RGB for high-bit-depth export.

        The develop pipeline carries full float precision; 16-bit output keeps that
        tonal resolution (smooth gradients, no banding) where the format allows it
        (TIFF/PNG), instead of collapsing every export to 256 levels.
        """
        return (clip01(self.data) * 65535.0 + 0.5).astype(np.uint16)

    def with_data(self, data: Array) -> ImageBuffer:
        return ImageBuffer(data, self.colorspace)
