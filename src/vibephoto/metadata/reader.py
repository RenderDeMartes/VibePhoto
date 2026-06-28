"""Image metadata reading (fast path).

Extracts dimensions and EXIF fields used for cataloguing, search, and HDR bracket
detection. This Phase-2 implementation uses Pillow, which covers JPEG/TIFF/PNG and
many embedded previews. RAW formats are handled by the dedicated ``raw`` layer in
Phase 3; for files Pillow cannot open, :meth:`MetadataReader.read` degrades to a
minimal result (no dimensions) rather than raising, so indexing never stalls on a
single file.

The reader is an injectable service with no catalog/UI dependencies, so it is
reusable from the indexer, batch tooling, and tests.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import ExifTags, Image, UnidentifiedImageError

logger = logging.getLogger(__name__)

# EXIF tag ids (avoids fragile name lookups across Pillow versions).
_TAG_MAKE = 271
_TAG_MODEL = 272
_TAG_ORIENTATION = 274
_TAG_DATETIME = 306  # top-level DateTime; fallback when DateTimeOriginal is absent
_EXIF_IFD = 0x8769
_GPS_IFD = 0x8825
_TAG_DATETIME_ORIGINAL = 36867
_TAG_ISO = 34855
_TAG_FNUMBER = 33437
_TAG_EXPOSURE_TIME = 33434
_TAG_FOCAL_LENGTH = 37386
_TAG_EXPOSURE_BIAS = 37380
_TAG_LENS_MODEL = 42036


@dataclass(slots=True)
class ImageInfo:
    """Dimensions + EXIF fields extracted from an image file."""

    width: int | None = None
    height: int | None = None
    orientation: int = 1
    capture_time: datetime | None = None
    camera_make: str | None = None
    camera_model: str | None = None
    lens: str | None = None
    iso: int | None = None
    aperture: float | None = None
    shutter: float | None = None
    focal_length: float | None = None
    exposure_bias: float | None = None
    gps_lat: float | None = None
    gps_lon: float | None = None


def _as_float(value: Any) -> float | None:
    # EXIF values are untyped at runtime (PIL IFDRational, int, str, tuple…).
    try:
        if value is None:
            return None
        return float(value)  # PIL IFDRational and numbers convert cleanly
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    f = _as_float(value)
    return int(f) if f is not None else None


def _parse_exif_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None


def _gps_to_degrees(coord: Any, ref: Any) -> float | None:
    try:
        d, m, s = (float(x) for x in coord)
    except (TypeError, ValueError):
        return None
    deg = d + m / 60.0 + s / 3600.0
    if isinstance(ref, str) and ref.upper() in ("S", "W"):
        deg = -deg
    return deg


class MetadataReader:
    """Reads :class:`ImageInfo` from image files. Stateless and thread-safe."""

    def read(self, path: Path) -> ImageInfo:
        """Read metadata from a file *path*.

        Returns an empty :class:`ImageInfo` (rather than raising) for anything
        Pillow cannot open, so indexing never stalls on one file. RAW files are
        handled by the ``raw`` layer, which extracts the embedded preview and
        calls :meth:`read_image` on it.
        """
        try:
            with Image.open(path) as img:
                return self.read_image(img)
        except (UnidentifiedImageError, OSError, ValueError):
            logger.debug("Pillow could not read metadata for %s", path)
            return ImageInfo()

    def read_image(self, img: Image.Image) -> ImageInfo:
        """Extract :class:`ImageInfo` from an already-open Pillow image.

        Shared by :meth:`read` and the ``raw`` layer (which opens a RAW file's
        embedded JPEG preview and reads its EXIF here), so EXIF parsing lives in
        exactly one place regardless of how the pixels were obtained.
        """
        info = ImageInfo()
        info.width, info.height = img.size
        exif = img.getexif()
        if not exif:
            return info

        info.camera_make = _clean(exif.get(_TAG_MAKE))
        info.camera_model = _clean(exif.get(_TAG_MODEL))
        orientation = _as_int(exif.get(_TAG_ORIENTATION))
        if orientation:
            info.orientation = orientation

        try:
            sub = exif.get_ifd(_EXIF_IFD)
        except Exception:  # noqa: BLE001 - some files have malformed IFDs
            sub = {}
        if sub:
            info.capture_time = _parse_exif_datetime(sub.get(_TAG_DATETIME_ORIGINAL))
            info.iso = _as_int(sub.get(_TAG_ISO))
            info.aperture = _as_float(sub.get(_TAG_FNUMBER))
            info.shutter = _as_float(sub.get(_TAG_EXPOSURE_TIME))
            info.focal_length = _as_float(sub.get(_TAG_FOCAL_LENGTH))
            info.exposure_bias = _as_float(sub.get(_TAG_EXPOSURE_BIAS))
            info.lens = _clean(sub.get(_TAG_LENS_MODEL))

        try:
            gps = exif.get_ifd(_GPS_IFD)
        except Exception:  # noqa: BLE001
            gps = {}
        if gps:
            # GPS IFD: 1=latRef 2=lat 3=lonRef 4=lon
            info.gps_lat = _gps_to_degrees(gps.get(2), gps.get(1))
            info.gps_lon = _gps_to_degrees(gps.get(4), gps.get(3))

        if info.capture_time is None:
            info.capture_time = _parse_exif_datetime(exif.get(_TAG_DATETIME))

        return info


def _clean(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().rstrip("\x00").strip()
    return text or None


# Pillow registers a richer tag map; expose for diagnostics/tests.
EXIF_TAG_NAMES = {v: k for k, v in ExifTags.TAGS.items()}
