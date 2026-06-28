"""Off-thread batch Auto-Edit runner.

Wraps :func:`vibephoto.processing.batch.auto_edit_photo` in a :class:`QRunnable` so a
whole selection can be auto-edited on a pool thread, reporting progress to the UI
without freezing it.
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

from PySide6.QtCore import QObject, QRunnable, Signal

from vibephoto.processing.batch import auto_edit_photo
from vibephoto.processing.loader import ImageLoader
from vibephoto.processing.store import DevelopStore


class BatchItem(NamedTuple):
    """One photo to auto-edit: its resolved path, catalog id, and RAW flag."""

    path: Path
    photo_id: int
    is_raw: bool


class BatchSignals(QObject):
    progress = Signal(int, int)  # (done, total)
    finished = Signal(int, int)  # (succeeded, total)
    failed = Signal(str)


class BatchAutoEditRunnable(QRunnable):
    """Auto-edits a list of photos on a pool thread, emitting progress."""

    def __init__(
        self, items: list[BatchItem], loader: ImageLoader, store: DevelopStore, kind: str = "edit"
    ) -> None:
        super().__init__()
        self._items = items
        self._loader = loader
        self._store = store
        self._kind = kind  # "edit" (auto-tone) or "hdr" (single-image HDR look)
        self.signals = BatchSignals()
        self.setAutoDelete(True)

    def run(self) -> None:
        total = len(self._items)
        succeeded = 0
        try:
            for index, item in enumerate(self._items, start=1):
                if auto_edit_photo(
                    self._loader, self._store, item.path, item.photo_id,
                    is_raw=item.is_raw, kind=self._kind,
                ):
                    succeeded += 1
                self.signals.progress.emit(index, total)
        except Exception as exc:  # noqa: BLE001 — report, never crash the pool thread
            self.signals.failed.emit(str(exc))
            return
        self.signals.finished.emit(succeeded, total)
