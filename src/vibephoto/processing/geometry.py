"""Crop & straighten — the photo-level geometry stage.

Geometry is a property of the *photo*, not of an adjustment layer: there is one
crop and one straighten angle, applied to the base image before the layer stack
develops it (mirroring professional RAW editors, where Crop sits outside the Basic/adjustment
panels). Keeping it on :class:`~vibephoto.processing.layers.LayerStack` rather than
in per-layer :class:`EditState` means layers compose over an already-cropped base
and never fight over conflicting crops.

The transform straightens first (rotate by ``angle``), then crops to a normalised
rectangle, so the crop is expressed in the straightened frame exactly as the UI
shows it. Rotation runs per-channel in float (PIL ``F`` mode) to preserve a
scene-linear buffer's range, the same discipline as the downscale path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image

from vibephoto.processing.image_buffer import ImageBuffer

try:  # OpenCV warpAffine rotates all channels in one SIMD multithreaded pass.
    import cv2
except ImportError:  # pragma: no cover - exercised on installs without the cv extra
    cv2 = None  # type: ignore[assignment]


@dataclass
class Geometry:
    """Photo-level crop + straighten. Defaults = identity (whole frame, no rotate).

    The crop is a normalised rectangle ``[0, 1]`` in the straightened frame:
    ``(left, top)`` to ``(right, bottom)``. ``angle`` is the straighten rotation in
    degrees (positive = counter-clockwise), small in practice (±45).
    """

    left: float = 0.0
    top: float = 0.0
    right: float = 1.0
    bottom: float = 1.0
    angle: float = 0.0
    rotate90: int = 0  # number of 90° counter-clockwise quarter-turns (0..3)

    def is_identity(self) -> bool:
        return (
            self.left == 0.0
            and self.top == 0.0
            and self.right == 1.0
            and self.bottom == 1.0
            and self.angle == 0.0
            and self.rotate90 % 4 == 0
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "left": self.left,
            "top": self.top,
            "right": self.right,
            "bottom": self.bottom,
            "angle": self.angle,
            "rotate90": self.rotate90,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Geometry:
        g = cls()
        if not isinstance(data, dict):
            return g
        g.left = _clamp01(data.get("left", 0.0))
        g.top = _clamp01(data.get("top", 0.0))
        g.right = _clamp01(data.get("right", 1.0))
        g.bottom = _clamp01(data.get("bottom", 1.0))
        g.angle = float(data.get("angle", 0.0))
        g.rotate90 = int(data.get("rotate90", 0)) % 4
        # Guard against an inverted/empty rect from a bad save.
        if g.right <= g.left:
            g.left, g.right = 0.0, 1.0
        if g.bottom <= g.top:
            g.top, g.bottom = 0.0, 1.0
        return g

    def copy(self) -> Geometry:
        return Geometry(
            self.left, self.top, self.right, self.bottom, self.angle, self.rotate90
        )


def _clamp01(value: Any) -> float:
    return float(min(1.0, max(0.0, float(value))))


def _rotate(data: np.ndarray, angle: float) -> np.ndarray:
    """Rotate ``(H, W, 3)`` float data by ``angle`` degrees, keeping the frame size.

    Bicubic in float so linear values survive; corners that rotate out of frame
    are filled with 0 (the crop is expected to exclude them). OpenCV rotates all
    channels in one pass when available; per-channel PIL ``F`` mode otherwise.
    """
    if cv2 is not None:
        height, width = data.shape[0], data.shape[1]
        matrix = cv2.getRotationMatrix2D(((width - 1) / 2.0, (height - 1) / 2.0), angle, 1.0)
        rotated = cv2.warpAffine(
            np.ascontiguousarray(data, dtype=np.float32),
            matrix,
            (width, height),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0.0,
        )
        return np.ascontiguousarray(rotated)
    channels = [
        np.asarray(
            Image.fromarray(data[..., c], mode="F").rotate(
                angle, resample=Image.Resampling.BICUBIC, expand=False, fillcolor=0.0
            ),
            dtype=np.float32,
        )
        for c in range(data.shape[2])
    ]
    return np.ascontiguousarray(np.stack(channels, axis=-1))


def apply_geometry(buffer: ImageBuffer, geometry: Geometry) -> ImageBuffer:
    """Rotate (90° steps), straighten, then crop ``buffer`` (identity = unchanged)."""
    if geometry.is_identity():
        return buffer
    data = buffer.data
    if geometry.rotate90 % 4:
        data = np.ascontiguousarray(np.rot90(data, geometry.rotate90 % 4))
    if geometry.angle != 0.0:
        data = _rotate(data, geometry.angle)
    height, width = data.shape[0], data.shape[1]
    x0 = round(geometry.left * width)
    x1 = round(geometry.right * width)
    y0 = round(geometry.top * height)
    y1 = round(geometry.bottom * height)
    x0, x1 = max(0, min(x0, width - 1)), max(1, min(x1, width))
    y0, y1 = max(0, min(y0, height - 1)), max(1, min(y1, height))
    if x1 <= x0:
        x0, x1 = 0, width
    if y1 <= y0:
        y0, y1 = 0, height
    cropped = np.ascontiguousarray(data[y0:y1, x0:x1])
    return ImageBuffer(cropped, buffer.colorspace)
