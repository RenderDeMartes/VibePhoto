"""Metadata layer — EXIF/IPTC/XMP read & write and the ExifTool integration.

Provides a uniform metadata model and adapters: fast embedded-EXIF reads for
indexing, and ExifTool-backed read/write for the long tail of formats and for
XMP sidecar synchronisation. The catalog uses this layer to populate searchable
fields; export uses it to apply metadata policy.

Depends on: ``core``. Never imports ``ui``.
Designed in: ``docs/04-database-schema.md`` (metadata tables) and the PRD.
Built in: Phase 2 (read) / Phase 8 (write policy).
"""

from __future__ import annotations

from vibephoto.metadata.reader import ImageInfo, MetadataReader

__all__ = ["ImageInfo", "MetadataReader"]
