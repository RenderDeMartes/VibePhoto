"""Filmstrip — a horizontal thumbnail strip along the bottom of the workspace.

Reuses :class:`PhotoGridModel` (so thumbnails and the catalog binding are shared
with the Library grid) laid out in a single scrolling row. Clicking a frame
selects it — and, in Develop, opens it for editing — the way the conventional filmstrip
lets you move through a shoot without leaving the editor.
"""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QSize, Qt, Signal
from PySide6.QtWidgets import QListView, QWidget

from vibephoto.catalog.models import Photo
from vibephoto.ui.photo_grid import GridDelegate, PhotoGridModel

_THUMB = 84


class Filmstrip(QListView):
    """A single-row, horizontally-scrolling thumbnail strip."""

    photo_clicked = Signal(object)  # Photo

    def __init__(self, model: PhotoGridModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = model
        self.setModel(model)
        self.setItemDelegate(GridDelegate(self))  # star-rating badge, like the grid
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(False)
        self.setIconSize(QSize(_THUMB, _THUMB))
        self.setGridSize(QSize(_THUMB + 14, _THUMB + 18))
        self.setFixedHeight(_THUMB + 34)
        self.setMovement(QListView.Movement.Static)
        self.setUniformItemSizes(True)
        self.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSpacing(2)
        self.clicked.connect(self._on_clicked)

    def _on_clicked(self, index: QModelIndex | QPersistentModelIndex) -> None:
        photo = self._model.photo_at(index.row())
        if photo is not None:
            self.photo_clicked.emit(photo)

    def select_photo(self, photo: Photo) -> None:
        """Highlight the frame for ``photo`` if it is present."""
        for row in range(self._model.rowCount()):
            current = self._model.photo_at(row)
            if current is not None and current.id == photo.id:
                self.setCurrentIndex(self._model.index(row, 0))
                return
