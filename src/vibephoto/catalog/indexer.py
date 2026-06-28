"""Incremental folder indexing.

Scans a folder, diffs it against the catalog, and imports new/changed photos,
reading metadata and queuing thumbnails. Designed to scale to 10k+ files without
blocking: it batches inserts inside one transaction, reports progress via events,
and re-syncs cheaply by skipping unchanged files (matched on size + mtime).

The indexer has no UI dependency; the UI triggers it through the application layer
and listens for :class:`IndexProgress` / :class:`IndexCompleted` events.
"""

from __future__ import annotations

import logging
import os
import uuid as uuidlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from vibephoto.catalog.events import IndexCompleted, IndexProgress, PhotoImported
from vibephoto.catalog.models import Photo, PhotoMetadata, PickStatus
from vibephoto.catalog.service import CatalogService
from vibephoto.core.events import EventBus
from vibephoto.metadata.reader import ImageInfo, MetadataReader
from vibephoto.raw.formats import RAW_EXTENSIONS, is_supported, normalize_ext
from vibephoto.raw.service import RawService
from vibephoto.utils.hashing import content_hash

logger = logging.getLogger(__name__)

#: Emit a progress event at most every N files (keeps the bus quiet on big imports).
_PROGRESS_EVERY = 25


@dataclass(slots=True)
class IndexResult:
    """Summary of an index/sync run."""

    folder: Path
    imported: int = 0
    skipped: int = 0
    failed: int = 0


class IndexerService:
    """Indexes filesystem folders into the active catalog."""

    def __init__(
        self,
        catalog: CatalogService,
        metadata_reader: MetadataReader,
        event_bus: EventBus,
        raw_service: RawService,
    ) -> None:
        self._catalog = catalog
        self._reader = metadata_reader
        self._events = event_bus
        self._raw = raw_service

    def index_folder(self, folder: Path, *, recursive: bool = True) -> IndexResult:
        """Index ``folder`` into the catalog and return a summary.

        Idempotent: already-imported, unchanged files are skipped, so re-running
        only picks up additions/changes.
        """
        folder = Path(folder).resolve()
        if not folder.is_dir():
            raise NotADirectoryError(folder)

        files = self._discover(folder, recursive=recursive)
        total = len(files)
        result = IndexResult(folder=folder)
        logger.info("Indexing %s (%d candidate files)", folder, total)

        # A stable volume per filesystem root keeps relinking robust. For Phase 2
        # we key the volume by the drive/anchor; a future phase reads real volume
        # UUIDs from the OS.
        volume = self._catalog.volumes.get_or_create(
            uuid=_volume_uuid(folder), label=folder.anchor or str(folder)
        )
        assert volume.id is not None

        for processed, file_path in enumerate(files, start=1):
            try:
                if self._index_one(file_path, volume.id):
                    result.imported += 1
                else:
                    result.skipped += 1
            except Exception:
                result.failed += 1
                logger.exception("Failed to index %s", file_path)

            if processed % _PROGRESS_EVERY == 0 or processed == total:
                self._events.publish(
                    IndexProgress(folder=folder, processed=processed, total=total)
                )

        self._events.publish(
            IndexCompleted(
                folder=folder,
                imported=result.imported,
                skipped=result.skipped,
                failed=result.failed,
            )
        )
        logger.info(
            "Indexed %s: %d imported, %d skipped, %d failed",
            folder, result.imported, result.skipped, result.failed,
        )
        return result

    # -- internals ---------------------------------------------------------- #

    def _discover(self, folder: Path, *, recursive: bool) -> list[Path]:
        walker = os.walk(folder) if recursive else [(str(folder), [], os.listdir(folder))]
        files: list[Path] = []
        for root, _dirs, names in walker:
            for name in names:
                if is_supported(name):
                    files.append(Path(root) / name)
        files.sort()
        return files

    def _index_one(self, file_path: Path, volume_id: int) -> bool:
        """Import one file. Returns True if imported, False if skipped (unchanged)."""
        parent = file_path.parent
        rel = _relative_to_volume(parent)
        folder = self._catalog.folders.get_or_create(
            volume_id=volume_id, path=rel, name=parent.name or str(parent)
        )
        assert folder.id is not None

        stat = file_path.stat()
        existing = self._catalog.photos.get_by_filename(folder.id, file_path.name)
        if existing is not None:
            mtime = datetime.fromtimestamp(stat.st_mtime)
            if existing.file_size == stat.st_size and existing.modified_time == mtime:
                if not existing.online:
                    self._catalog.photos.set_online(existing.id or 0, True)
                return False  # unchanged

        ext = normalize_ext(file_path.name)
        info = self._read_info(file_path, ext)
        photo = Photo(
            folder_id=folder.id,
            filename=file_path.name,
            file_ext=ext,
            import_time=datetime.now(),
            file_size=stat.st_size,
            content_hash=content_hash(file_path),
            is_raw=ext in RAW_EXTENSIONS,
            capture_time=info.capture_time,
            modified_time=datetime.fromtimestamp(stat.st_mtime),
            orientation=info.orientation,
            width=info.width,
            height=info.height,
            pick_status=PickStatus.NONE,
        )
        # One transaction: photo + FTS + metadata land atomically.
        with self._catalog.db.transaction():
            photo_id = self._catalog.photos.insert(photo)
            self._catalog.photos.set_metadata(_to_metadata(photo_id, info))

        self._events.publish(PhotoImported(photo_id=photo_id, path=file_path))
        return True

    def _read_info(self, file_path: Path, ext: str) -> ImageInfo:
        """Read metadata, routing RAW files through the RAW layer.

        Falls back to the Pillow reader when RAW support is unavailable or the
        decoder cannot read the file, so indexing degrades gracefully rather than
        leaving a RAW with no metadata at all.
        """
        if ext in RAW_EXTENSIONS and self._raw.available:
            info = self._raw.read_metadata(file_path)
            if info is not None:
                return info
        return self._reader.read(file_path)


def _to_metadata(photo_id: int, info: ImageInfo) -> PhotoMetadata:
    return PhotoMetadata(
        photo_id=photo_id,
        camera_make=info.camera_make,
        camera_model=info.camera_model,
        lens=info.lens,
        iso=info.iso,
        aperture=info.aperture,
        shutter=info.shutter,
        focal_length=info.focal_length,
        exposure_bias=info.exposure_bias,
        gps_lat=info.gps_lat,
        gps_lon=info.gps_lon,
    )


def _relative_to_volume(folder: Path) -> str:
    """Path of ``folder`` relative to its volume anchor (drive/mount root)."""
    anchor = Path(folder.anchor) if folder.anchor else None
    if anchor is not None:
        try:
            return str(folder.relative_to(anchor))
        except ValueError:
            pass
    return str(folder)


def _volume_uuid(path: Path) -> str:
    """Derive a stable per-volume id. Phase 2: namespaced on the anchor string.

    A later phase replaces this with the real OS volume UUID for robust relinking
    across mount-point changes.
    """
    anchor = path.anchor or str(path)
    return str(uuidlib.uuid5(uuidlib.NAMESPACE_URL, f"volume:{anchor}"))
