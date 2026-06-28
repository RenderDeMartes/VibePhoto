"""Thumbnail cache — disk-backed with an in-memory LRU.

Generates square-fit JPEG thumbnails on demand and persists them under the cache
directory, sharded by key prefix to avoid huge flat directories. A bounded
in-memory LRU keeps recently shown thumbnails hot for smooth grid scrolling. The
cache is keyed by content hash, so a moved/renamed file reuses its thumbnail.

No Qt dependency: the cache returns file paths / raw JPEG bytes; the UI converts
those to ``QPixmap``. RAW files (which Pillow cannot decode) are thumbnailed from
their embedded JPEG preview via the injected :class:`RawService`; when no RAW
support is available the cache returns ``None`` and the grid shows a placeholder.
"""

from __future__ import annotations

import io
import logging
import threading
from collections import OrderedDict
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from vibephoto.core.config import CacheSettings
from vibephoto.core.paths import AppPaths
from vibephoto.raw.formats import is_raw_extension
from vibephoto.raw.service import RawService

logger = logging.getLogger(__name__)

DEFAULT_THUMB_SIZE = 256
#: Cap the RAM-resident LRU independently of the (larger) on-disk budget.
_MEMORY_BUDGET_BYTES = 256 * 1024 * 1024


class ThumbnailCache:
    """Generates and caches thumbnails. Thread-safe."""

    def __init__(
        self,
        paths: AppPaths,
        settings: CacheSettings,
        raw_service: RawService | None = None,
    ) -> None:
        self._root = paths.thumbnails_dir
        self._quality = settings.preview_quality
        self._raw = raw_service
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._memory: OrderedDict[str, bytes] = OrderedDict()
        self._memory_bytes = 0

    def path_for(self, key: str, size: int = DEFAULT_THUMB_SIZE) -> Path:
        """Deterministic on-disk location for a thumbnail key + size."""
        safe = key.replace(":", "_")
        return self._root / safe[:2] / f"{safe}_{size}.jpg"

    def get_or_create(
        self, source: Path, key: str, size: int = DEFAULT_THUMB_SIZE
    ) -> Path | None:
        """Return the thumbnail path, generating it if absent. ``None`` on failure."""
        dest = self.path_for(key, size)
        if dest.exists():
            return dest
        return self._generate(source, dest, size)

    def get_bytes(self, key: str, size: int = DEFAULT_THUMB_SIZE) -> bytes | None:
        """Return thumbnail JPEG bytes from the LRU/disk, or ``None`` if absent."""
        cache_key = f"{key}_{size}"
        with self._lock:
            data = self._memory.get(cache_key)
            if data is not None:
                self._memory.move_to_end(cache_key)
                return data
        dest = self.path_for(key, size)
        if not dest.exists():
            return None
        data = dest.read_bytes()
        self._remember(cache_key, data)
        return data

    def _generate(self, source: Path, dest: Path, size: int) -> Path | None:
        image = self._load(source)
        if image is None:
            logger.debug("Could not generate thumbnail for %s", source)
            return None
        try:
            with image:
                oriented = ImageOps.exif_transpose(image) or image  # honour orientation
                oriented.thumbnail((size, size), Image.Resampling.LANCZOS)
                rgb = oriented.convert("RGB")
                dest.parent.mkdir(parents=True, exist_ok=True)
                rgb.save(dest, format="JPEG", quality=self._quality)
        except (OSError, ValueError):
            logger.debug("Could not generate thumbnail for %s", source)
            return None
        self._remember(f"{_key_from_path(dest)}_{size}", dest.read_bytes())
        return dest

    def _load(self, source: Path) -> Image.Image | None:
        """Open ``source`` as a Pillow image, falling back to a RAW embedded
        preview for camera RAW files Pillow cannot decode. ``None`` on failure."""
        try:
            image = Image.open(source)
            image.load()  # force decode now so failures surface here, not mid-resize
            return image
        except (UnidentifiedImageError, OSError, ValueError):
            pass
        if self._raw is not None and is_raw_extension(source.suffix):
            data = self._raw.load_preview(source)
            if data:
                try:
                    image = Image.open(io.BytesIO(data))
                    image.load()
                    return image
                except (UnidentifiedImageError, OSError, ValueError):
                    return None
        return None

    def _remember(self, cache_key: str, data: bytes) -> None:
        with self._lock:
            if cache_key in self._memory:
                self._memory_bytes -= len(self._memory[cache_key])
            self._memory[cache_key] = data
            self._memory.move_to_end(cache_key)
            self._memory_bytes += len(data)
            while self._memory_bytes > _MEMORY_BUDGET_BYTES and self._memory:
                _, evicted = self._memory.popitem(last=False)
                self._memory_bytes -= len(evicted)

    @property
    def memory_bytes(self) -> int:
        """Current RAM held by the in-memory LRU (for diagnostics/tests)."""
        return self._memory_bytes


def _key_from_path(dest: Path) -> str:
    # Reconstruct the key portion from "<key>_<size>.jpg"; only used for the
    # generate-path warm insert, which is best-effort.
    return dest.stem.rsplit("_", 1)[0]
