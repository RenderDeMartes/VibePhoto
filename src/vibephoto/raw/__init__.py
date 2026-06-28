"""RAW layer — decoding and preview extraction for camera RAW formats.

Wraps LibRaw (via rawpy) and embedded-preview extraction to provide a uniform
``RawImage`` abstraction over CR2/CR3/NEF/ARW/DNG/RAF/RW2/ORF/PEF. Exposes a
pluggable decoder registry so new formats/backends can be added without touching
callers. Provides fast embedded-JPEG previews for the library grid and full
decode (with camera metadata) for the develop pipeline.

Depends on: ``core``, ``metadata``. Never imports ``ui``.
Designed in: ``docs/06-processing-engine.md`` (RAW Decode stage).
Built in: Phase 3.
"""

from __future__ import annotations

from vibephoto.raw.decoder import (
    DecoderRegistry,
    RawDecoder,
    RawImage,
    RawInspection,
    RawpyDecoder,
    default_registry,
)
from vibephoto.raw.formats import (
    IMAGE_EXTENSIONS,
    RAW_EXTENSIONS,
    SUPPORTED_EXTENSIONS,
    is_raw_extension,
    is_supported,
    normalize_ext,
)
from vibephoto.raw.service import RawService

__all__ = [
    "IMAGE_EXTENSIONS",
    "RAW_EXTENSIONS",
    "SUPPORTED_EXTENSIONS",
    "DecoderRegistry",
    "RawDecoder",
    "RawImage",
    "RawInspection",
    "RawService",
    "RawpyDecoder",
    "default_registry",
    "is_raw_extension",
    "is_supported",
    "normalize_ext",
]
