"""Export layer — render-to-file with presets, resizing, and watermarking.

Renders edited photos through the processing pipeline at export resolution and
writes JPG/PNG/TIFF/DNG/HDR with configurable colour space, metadata policy,
resize, sharpening-for-output, and watermarks. Ships export presets (Web,
Instagram, MLS, Real Estate, Print, Full Resolution) and runs as asynchronous
batch jobs.

Depends on: ``core``, ``processing``, ``metadata``, ``catalog``. Never imports ``ui``.
Designed in: ``docs/06-processing-engine.md`` (Output stage) and the PRD.
Built in: Phase 8.
"""

from __future__ import annotations

from vibephoto.export.presets import BUILTIN_EXPORT_PRESETS, ExportPreset
from vibephoto.export.service import ExportItem, ExportResult, ExportService
from vibephoto.export.writers import apply_watermark, resize_to_long_edge, write_image

__all__ = [
    "BUILTIN_EXPORT_PRESETS",
    "ExportItem",
    "ExportPreset",
    "ExportResult",
    "ExportService",
    "apply_watermark",
    "resize_to_long_edge",
    "write_image",
]
