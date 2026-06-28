"""Supported image and RAW file formats.

Centralises format knowledge in the ``raw`` layer so the indexer, importer, and
(Phase 3) decoders agree on what is a RAW file vs. a rendered image. Extensions
are lower-case, without the leading dot.
"""

from __future__ import annotations

from typing import Final

#: RAW formats targeted by Vibe Photo (see PRD).
RAW_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {"cr2", "cr3", "nef", "arw", "dng", "raf", "rw2", "orf", "pef"}
)

#: Rendered/standard image formats readable in Phase 2 via Pillow.
IMAGE_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {"jpg", "jpeg", "png", "tif", "tiff", "webp", "heic", "heif", "bmp"}
)

#: Everything the catalog will ingest.
SUPPORTED_EXTENSIONS: Final[frozenset[str]] = RAW_EXTENSIONS | IMAGE_EXTENSIONS


def normalize_ext(name: str) -> str:
    """Return the lower-case extension of a filename, without the dot."""
    _, _, ext = name.rpartition(".")
    return ext.lower()


def is_raw_extension(ext: str) -> bool:
    return ext.lstrip(".").lower() in RAW_EXTENSIONS


def is_supported(name: str) -> bool:
    return normalize_ext(name) in SUPPORTED_EXTENSIONS
