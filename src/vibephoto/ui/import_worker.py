"""Background import worker.

Runs a folder index — and warms thumbnails for the imported photos — off the GUI
thread via Qt's ``QThreadPool``. The indexer itself emits progress/completion
events on the core bus (surfaced to the UI by :class:`QtEventBridge`); this worker
adds a ``finished`` Qt signal carrying the :class:`IndexResult` once thumbnails are
warmed, so the grid only refreshes when images are ready to display.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal

from vibephoto.cache.thumbnails import ThumbnailCache
from vibephoto.catalog.indexer import IndexerService
from vibephoto.catalog.service import CatalogService

logger = logging.getLogger(__name__)


class ImportSignals(QObject):
    """Signals emitted by an :class:`ImportRunnable` (lives on the GUI thread)."""

    finished = Signal(object)  # IndexResult
    failed = Signal(str)


class ImportRunnable(QRunnable):
    """Indexes ``folder`` then warms thumbnails; emits ``finished`` when done."""

    def __init__(
        self,
        folder: Path,
        indexer: IndexerService,
        catalog: CatalogService,
        thumbnails: ThumbnailCache,
    ) -> None:
        super().__init__()
        self._folder = folder
        self._indexer = indexer
        self._catalog = catalog
        self._thumbnails = thumbnails
        self.signals = ImportSignals()

    def run(self) -> None:
        try:
            result = self._indexer.index_folder(self._folder)
            self._warm_thumbnails()
        except Exception as exc:
            logger.exception("Import failed for %s", self._folder)
            self.signals.failed.emit(str(exc))
            return
        self.signals.finished.emit(result)

    def _warm_thumbnails(self) -> None:
        for photo in self._catalog.photos.list_all():
            if not photo.content_hash:
                continue
            source = self._catalog.resolve_path(photo)
            if source is not None and source.exists():
                self._thumbnails.get_or_create(source, photo.content_hash)
