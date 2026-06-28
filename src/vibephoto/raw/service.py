"""RawService — the application-facing façade over the RAW decoder registry.

Injected into the indexer (for camera metadata) and the thumbnail cache (for
embedded-preview thumbnails). Stateless and thread-safe; every method degrades to
``None`` instead of raising, so one unreadable RAW never stalls an import or a
grid repaint. When rawpy is not installed, :attr:`available` is ``False`` and all
methods return ``None`` — callers fall back to placeholders / Pillow.

Camera metadata is read from the RAW's *embedded JPEG preview* via the shared
:class:`MetadataReader`, then the master pixel dimensions and orientation are
overlaid from LibRaw — so EXIF parsing is not duplicated and dimensions reflect
the full-resolution master rather than the (smaller) preview.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from vibephoto.metadata.reader import ImageInfo, MetadataReader
from vibephoto.raw import colortemp
from vibephoto.raw.decoder import DecoderRegistry, RawDecoder, RawImage, default_registry
from vibephoto.raw.formats import normalize_ext

logger = logging.getLogger(__name__)

#: LibRaw orientation flag -> EXIF orientation (1..8). Used only when the embedded
#: preview carries no orientation of its own.
_FLIP_TO_ORIENTATION: dict[int, int] = {0: 1, 3: 3, 5: 8, 6: 6}


class RawService:
    """Decode RAW previews, metadata, and full rasters via the decoder registry."""

    def __init__(self, registry: DecoderRegistry | None = None) -> None:
        self._registry = registry if registry is not None else default_registry()
        self._meta = MetadataReader()

    @property
    def available(self) -> bool:
        """True when RAW decoding is available (rawpy installed / a decoder present)."""
        return self._registry.available

    def supports(self, path: Path) -> bool:
        """Whether a registered decoder handles ``path``'s extension."""
        return self._decoder(path) is not None

    def load_preview(self, path: Path) -> bytes | None:
        """Return the RAW's embedded JPEG preview (for thumbnailing), or ``None``."""
        decoder = self._decoder(path)
        if decoder is None:
            return None
        inspection = decoder.inspect(Path(path))
        return inspection.preview if inspection is not None else None

    def read_metadata(self, path: Path) -> ImageInfo | None:
        """Read dimensions + EXIF for a RAW file, or ``None`` if unsupported.

        EXIF comes from the embedded preview; ``width``/``height`` and (when the
        preview has none) orientation come from LibRaw, describing the master.
        """
        decoder = self._decoder(path)
        if decoder is None:
            return None
        inspection = decoder.inspect(Path(path))
        if inspection is None:
            return None
        info = self._info_from_preview(inspection.preview)
        info.width = inspection.width
        info.height = inspection.height
        if info.orientation == 1:  # preview carried no orientation; use LibRaw's
            info.orientation = _FLIP_TO_ORIENTATION.get(inspection.flip, 1)
        return info

    def as_shot_temperature(self, path: Path) -> float | None:
        """Estimate the as-shot colour temperature (Kelvin) from camera calibration."""
        decoder = self._decoder(path)
        if decoder is None:
            return None
        inspection = decoder.inspect(Path(path))
        if inspection is None or inspection.camera_wb is None or inspection.xyz_to_cam is None:
            return None
        return colortemp.as_shot_temperature(inspection.camera_wb, inspection.xyz_to_cam)

    def decode(self, path: Path, *, half_size: bool = False) -> RawImage | None:
        """Full LibRaw decode to a display-oriented 16-bit RGB raster, or ``None``.

        ``half_size`` requests a faster half-resolution demosaic for live previews.
        """
        decoder = self._decoder(path)
        if decoder is None:
            return None
        return decoder.decode(Path(path), half_size=half_size)

    # -- internals ---------------------------------------------------------- #

    def _decoder(self, path: Path) -> RawDecoder | None:
        return self._registry.decoder_for(normalize_ext(Path(path).name))

    def _info_from_preview(self, preview: bytes | None) -> ImageInfo:
        if preview is None:
            return ImageInfo()
        try:
            with Image.open(io.BytesIO(preview)) as img:
                return self._meta.read_image(img)
        except (UnidentifiedImageError, OSError, ValueError):
            return ImageInfo()
