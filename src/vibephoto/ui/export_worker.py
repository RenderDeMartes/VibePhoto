"""Background export worker.

Runs :meth:`ExportService.export_many` off the GUI thread via ``QThreadPool``,
re-emitting progress and completion as Qt signals so the main window can update
the status bar without touching widgets from a worker thread.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal

from vibephoto.export.presets import ExportPreset
from vibephoto.export.service import ExportItem, ExportService

logger = logging.getLogger(__name__)


class ExportSignals(QObject):
    """Signals emitted by an :class:`ExportRunnable` (lives on the GUI thread)."""

    progress = Signal(int, int)  # done, total
    finished = Signal(object)  # ExportResult
    failed = Signal(str)


class ExportRunnable(QRunnable):
    """Exports a batch of photos, emitting progress and a final result."""

    def __init__(
        self,
        service: ExportService,
        items: list[ExportItem],
        preset: ExportPreset,
        dest_dir: Path,
    ) -> None:
        super().__init__()
        self._service = service
        self._items = items
        self._preset = preset
        self._dest = dest_dir
        self.signals = ExportSignals()

    def run(self) -> None:
        try:
            result = self._service.export_many(
                self._items, self._preset, self._dest, progress=self.signals.progress.emit
            )
        except Exception as exc:
            logger.exception("Export failed")
            self.signals.failed.emit(str(exc))
            return
        self.signals.finished.emit(result)
