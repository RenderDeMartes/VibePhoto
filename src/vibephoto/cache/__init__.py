"""Cache layer — thumbnails, standard previews, and smart previews.

A multi-tier, size-budgeted cache that backs smooth grid scrolling and offline
editing. Thumbnails and 1:1/standard previews are generated on background
workers and persisted to disk; smart previews are compressed, reduced-resolution
proxies (lossy DNG-style) that allow editing while originals are offline. The
cache enforces byte budgets with LRU eviction.

Depends on: ``core``, ``raw``, ``processing``. Never imports ``ui``.
Designed in: ``docs/11-performance-strategy.md`` and the Smart Preview section of the PRD.
Built in: Phase 2 (thumbnails/previews) / Phase 3 (smart previews).
"""

from __future__ import annotations

from vibephoto.cache.thumbnails import DEFAULT_THUMB_SIZE, ThumbnailCache

__all__ = ["DEFAULT_THUMB_SIZE", "ThumbnailCache"]
