"""Smart-preview cache — decoded RAW base buffers, disk-backed with a RAM LRU.

Opening a RAW in Develop costs a multi-second LibRaw decode. The decoded
preview-sized scene-linear base (plus the camera's as-shot temperature) is
deterministic per file content, so it is cached here: ``float16`` on disk keyed
by content hash, with a small RAM LRU so arrow-key browsing between neighbouring
photos is instant. A cached open takes ~100 ms instead of seconds; export is
unaffected (it always decodes the full-resolution RAW).

No Qt dependency — usable headless. Thread-safe.
"""

from __future__ import annotations

import logging
import os
import threading
import zipfile
from collections import OrderedDict
from pathlib import Path

import numpy as np

from vibephoto.core.config import CacheSettings
from vibephoto.core.paths import AppPaths
from vibephoto.processing.image_buffer import ImageBuffer

logger = logging.getLogger(__name__)

#: Bump when the stored format (or the decode it captures) changes; old entries
#: are simply never matched again and age out via the size budget.
_FORMAT_VERSION = 1

#: RAM-resident entries (a 2048px float32 base is ~33 MB; 4 ≈ 130 MB ceiling).
_MEMORY_SLOTS = 4


class PreviewCache:
    """Caches preview-sized decoded base buffers ("smart previews")."""

    def __init__(self, paths: AppPaths, settings: CacheSettings) -> None:
        self._root = paths.previews_dir
        self._budget_bytes = settings.max_preview_cache_mb * 1024 * 1024
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._memory: OrderedDict[str, tuple[ImageBuffer, float | None]] = OrderedDict()

    def _path_for(self, key: str) -> Path:
        safe = key.replace(":", "_")
        return self._root / safe[:2] / f"{safe}_v{_FORMAT_VERSION}.npz"

    def contains(self, key: str) -> bool:
        """True when a preview for ``key`` is in RAM or on disk (no decode needed)."""
        with self._lock:
            if key in self._memory:
                return True
        return self._path_for(key).is_file()

    def load(self, key: str) -> tuple[ImageBuffer, float | None] | None:
        """Return ``(base buffer, as-shot Kelvin | None)`` for ``key``, or ``None``."""
        with self._lock:
            hit = self._memory.get(key)
            if hit is not None:
                self._memory.move_to_end(key)
                return hit
        path = self._path_for(key)
        if not path.is_file():
            return None
        try:
            with np.load(path) as archive:
                data = archive["data"].astype(np.float32)
                colorspace = str(archive["colorspace"])
                as_shot_raw = float(archive["as_shot"])
        except (OSError, ValueError, KeyError, zipfile.BadZipFile):
            logger.debug("Unreadable preview cache entry %s", path, exc_info=True)
            return None
        buffer = ImageBuffer(np.ascontiguousarray(data), colorspace)
        as_shot = None if np.isnan(as_shot_raw) else as_shot_raw
        self._remember(key, buffer, as_shot)
        return (buffer, as_shot)

    def save(self, key: str, buffer: ImageBuffer, as_shot: float | None) -> None:
        """Persist a decoded base (float16 — ample for a preview-sized proxy)."""
        path = self._path_for(key)
        tmp = path.with_suffix(".tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp, "wb") as handle:
                np.savez(
                    handle,
                    data=buffer.data.astype(np.float16),
                    colorspace=np.asarray(buffer.colorspace),
                    as_shot=np.float64(np.nan if as_shot is None else as_shot),
                )
            os.replace(tmp, path)  # atomic: readers never see a half-written entry
        except OSError:
            logger.debug("Could not persist preview cache entry %s", path, exc_info=True)
            tmp.unlink(missing_ok=True)
            return
        self._remember(key, buffer, as_shot)
        self._evict_over_budget()

    def _remember(self, key: str, buffer: ImageBuffer, as_shot: float | None) -> None:
        with self._lock:
            self._memory[key] = (buffer, as_shot)
            self._memory.move_to_end(key)
            while len(self._memory) > _MEMORY_SLOTS:
                self._memory.popitem(last=False)

    def _evict_over_budget(self) -> None:
        """Delete the oldest disk entries until the cache fits its byte budget."""
        try:
            entries = [
                (entry.stat().st_mtime, entry.stat().st_size, entry)
                for entry in self._root.rglob("*.npz")
            ]
        except OSError:
            return
        total = sum(size for _, size, _ in entries)
        if total <= self._budget_bytes:
            return
        for _, size, entry in sorted(entries):  # oldest first
            entry.unlink(missing_ok=True)
            total -= size
            if total <= self._budget_bytes:
                break
