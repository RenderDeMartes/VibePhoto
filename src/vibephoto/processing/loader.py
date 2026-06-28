"""Load a photo's pixels into an editable :class:`ImageBuffer`.

RAW files are decoded through LibRaw to the **real demosaiced sensor data** (16-bit,
camera white balance) — so editing works on the RAW like professional RAW editors, not on the
camera's flattened 8-bit JPEG. For the live preview the decode is *half-size*
(fast) and downsized to a preview long-edge; export and 1:1 zoom request the full
decode (``full=True``). The same decode backs both, so the preview matches the
export. The camera's embedded JPEG is used only as a fallback when the real decode
is unavailable or fails. For rendered files (JPEG/PNG/TIFF) Pillow loads the pixels
and EXIF orientation is honoured so portraits load upright.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from vibephoto.processing.image_buffer import ImageBuffer
from vibephoto.processing.resample import downscale_buffer
from vibephoto.raw.service import RawService

logger = logging.getLogger(__name__)

DEFAULT_PREVIEW_LONG_EDGE = 2048  # canvas preview long edge (a bit higher res)


class ImageLoader:
    """Decodes a file path into an oriented, preview-sized RGB buffer."""

    def __init__(self, raw_service: RawService) -> None:
        self._raw = raw_service

    def load(
        self,
        path: Path,
        *,
        is_raw: bool,
        long_edge: int = DEFAULT_PREVIEW_LONG_EDGE,
        full: bool = False,
    ) -> ImageBuffer | None:
        """Return an oriented :class:`ImageBuffer`, or ``None`` on failure.

        RAW files decode through LibRaw (the real sensor data); ``full=True``
        requests the full-resolution demosaic (export / 1:1 zoom) while the default
        uses a fast half-size demosaic for previews. ``long_edge`` still caps the
        result (0 = no downscale).
        """
        if is_raw and self._raw.available:
            buffer = self._decode_raw(path, long_edge=long_edge, full=full)
            if buffer is not None:
                return buffer
            # The real decode failed — fall back to the embedded preview / Pillow.

        image = self._open(path, is_raw=is_raw)
        if image is None:
            return None
        try:
            with image:
                oriented = ImageOps.exif_transpose(image) or image
                rgb = oriented.convert("RGB")
                if long_edge > 0:
                    rgb.thumbnail((long_edge, long_edge), Image.Resampling.LANCZOS)
                array = np.asarray(rgb, dtype=np.uint8)
        except (OSError, ValueError):
            logger.debug("Failed to load image %s", path, exc_info=True)
            return None
        return ImageBuffer.from_uint8(array)

    def _decode_raw(self, path: Path, *, long_edge: int, full: bool) -> ImageBuffer | None:
        """Decode a RAW to a float buffer via LibRaw, or ``None`` on failure.

        Previews use a half-size demosaic (fast); ``full`` requests the full decode.
        LibRaw returns a display-oriented raster, so no extra EXIF rotation is needed.
        """
        decoded = self._raw.decode(path, half_size=not full)
        if decoded is None:
            return None
        # Tag the buffer scene-linear so the pipeline runs the RAW develop front-end;
        # downscale in float to keep the linear values (a uint8 round trip would not).
        linear = ImageBuffer.from_uint16(decoded.rgb, colorspace="linear")
        return downscale_buffer(linear, long_edge)

    def _open(self, path: Path, *, is_raw: bool) -> Image.Image | None:
        if is_raw and self._raw.available:
            data = self._raw.load_preview(path)
            if data:
                try:
                    return Image.open(io.BytesIO(data))
                except (UnidentifiedImageError, OSError, ValueError):
                    logger.debug("RAW preview unreadable for %s", path, exc_info=True)
        try:
            return Image.open(path)
        except (UnidentifiedImageError, OSError, ValueError):
            logger.debug("Pillow could not open %s", path, exc_info=True)
            return None
