"""Bridge between the core :class:`EventBus` and Qt signals.

The catalog/indexer publish events from background threads. Touching widgets off
the GUI thread is undefined behaviour in Qt, so this adapter subscribes to the
bus and re-emits Qt signals. Because the bridge object lives on the GUI thread,
a signal emitted from a worker thread is delivered to connected slots via a
queued connection — i.e. marshalled onto the GUI thread automatically. This is
the one place that knows about both the bus and Qt, keeping the rest of the UI
free of threading concerns and the core free of Qt.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from vibephoto.catalog.events import (
    CatalogOpened,
    IndexCompleted,
    IndexProgress,
    PhotoImported,
)
from vibephoto.core.events import EventBus


class QtEventBridge(QObject):
    """Re-emits selected catalog events as GUI-thread Qt signals."""

    catalog_opened = Signal(object)  # CatalogOpened
    index_progress = Signal(object)  # IndexProgress
    index_completed = Signal(object)  # IndexCompleted
    photo_imported = Signal(object)  # PhotoImported

    def __init__(self, event_bus: EventBus) -> None:
        super().__init__()
        # Keep the Subscription handles alive for the bridge's lifetime.
        self._subs = [
            event_bus.subscribe(CatalogOpened, self.catalog_opened.emit),
            event_bus.subscribe(IndexProgress, self.index_progress.emit),
            event_bus.subscribe(IndexCompleted, self.index_completed.emit),
            event_bus.subscribe(PhotoImported, self.photo_imported.emit),
        ]
