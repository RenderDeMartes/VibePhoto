"""HDR layer — bracket detection, alignment, deghosting, and merge.

Implements the flagship HDR and Real-Estate Auto Process workflows: detect
bracket groups by EXIF timing/exposure, align frames, remove ghosting, merge to
a high-bit-depth radiance image, and hand off to the processing pipeline for
tone mapping and preset application. Runs entirely headless and is invoked by
batch jobs as well as the UI.

Depends on: ``core``, ``raw``, ``processing``, ``metadata``. Never imports ``ui``.
Designed in: ``docs/07-hdr-pipeline.md``.
Built in: Phase 6.
"""

from __future__ import annotations

__all__: list[str] = []
