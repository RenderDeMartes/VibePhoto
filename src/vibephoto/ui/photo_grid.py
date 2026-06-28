"""The Library thumbnail grid: model + view.

``PhotoGridModel`` adapts a list of :class:`Photo` to Qt's model/view, sourcing
thumbnails from the (already-warmed) :class:`ThumbnailCache` as JPEG bytes and
converting them to ``QPixmap`` lazily, with a per-photo pixmap cache so repeated
repaints during scrolling are cheap. A :class:`GridDelegate` overlays the star
rating; ``LibraryGrid`` (an icon-mode ``QListView``) emits ``rating_key`` when the
0-5 keys are pressed, the professional RAW editors way to rate the selection.
"""

from __future__ import annotations

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QPersistentModelIndex,
    QRect,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QKeyEvent, QPainter, QPixmap
from PySide6.QtWidgets import QListView, QStyledItemDelegate, QStyleOptionViewItem, QWidget

from vibephoto.cache.thumbnails import DEFAULT_THUMB_SIZE, ThumbnailCache
from vibephoto.catalog.models import Photo

_ICON = 180
_Index = QModelIndex | QPersistentModelIndex
_NO_PARENT = QModelIndex()

#: Custom model role carrying a photo's star rating (0..5).
RATING_ROLE = int(Qt.ItemDataRole.UserRole) + 1

#: Keyboard key code -> star rating (0..5), professional.
_RATING_KEYS = {int(Qt.Key.Key_0.value) + n: n for n in range(6)}


def _make_placeholder(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(QColor("#2f3236"))
    painter = QPainter(pm)
    painter.setPen(QColor("#4a4e54"))
    painter.drawRect(0, 0, size - 1, size - 1)
    painter.end()
    return pm


class PhotoGridModel(QAbstractListModel):
    """List model over catalog photos, decorated with cached thumbnails."""

    def __init__(self, thumbnails: ThumbnailCache, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._thumbnails = thumbnails
        self._photos: list[Photo] = []
        self._pixmaps: dict[int, QPixmap] = {}
        self._placeholder = _make_placeholder(_ICON)

    def set_photos(self, photos: list[Photo]) -> None:
        self.beginResetModel()
        self._photos = photos
        self._pixmaps.clear()
        self.endResetModel()

    def photos(self) -> list[Photo]:
        return self._photos

    def photo_at(self, row: int) -> Photo | None:
        """Return the photo at ``row``, or ``None`` if out of range."""
        if 0 <= row < len(self._photos):
            return self._photos[row]
        return None

    def update_rating(self, row: int, rating: int) -> None:
        """Set the rating on the photo at ``row`` and repaint it."""
        if 0 <= row < len(self._photos):
            self._photos[row].rating = rating
            index = self.index(row, 0)
            self.dataChanged.emit(
                index, index, [RATING_ROLE, Qt.ItemDataRole.ToolTipRole]
            )

    def rowCount(self, parent: _Index = _NO_PARENT) -> int:
        return 0 if parent.isValid() else len(self._photos)

    def data(self, index: _Index, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        if not index.isValid() or not (0 <= index.row() < len(self._photos)):
            return None
        photo = self._photos[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return photo.filename
        if role == Qt.ItemDataRole.DecorationRole:
            return self._pixmap_for(photo)
        if role == RATING_ROLE:
            return photo.rating
        if role == Qt.ItemDataRole.ToolTipRole:
            dims = f"{photo.width}x{photo.height}" if photo.width else "-"
            stars = "★" * photo.rating if photo.rating else "unrated"
            return f"{photo.filename}\n{dims}   {stars}"
        return None

    def _pixmap_for(self, photo: Photo) -> QPixmap:
        pid = photo.id or 0
        cached = self._pixmaps.get(pid)
        if cached is not None:
            return cached
        pixmap = self._placeholder
        if photo.content_hash:
            data = self._thumbnails.get_bytes(photo.content_hash, DEFAULT_THUMB_SIZE)
            if data:
                candidate = QPixmap()
                if candidate.loadFromData(data) and not candidate.isNull():
                    pixmap = candidate
        self._pixmaps[pid] = pixmap
        return pixmap


class GridDelegate(QStyledItemDelegate):
    """Draws the default item plus a star-rating badge in the top-left corner."""

    def paint(
        self, painter: QPainter, option: QStyleOptionViewItem, index: _Index
    ) -> None:
        super().paint(painter, option, index)
        rating = index.data(RATING_ROLE)
        if not isinstance(rating, int) or rating <= 0:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont(option.font)
        font.setPointSize(9)
        painter.setFont(font)
        badge = QRect(option.rect.left() + 8, option.rect.top() + 8, 13 * rating + 8, 18)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 150))
        painter.drawRoundedRect(badge, 4, 4)
        painter.setPen(QColor("#ffce47"))
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, "★" * rating)
        painter.restore()


class LibraryGrid(QListView):
    """A thumbnail grid view configured for fluid browsing."""

    rating_key = Signal(int)  # 0..5, from pressing the number keys

    def __init__(self, model: PhotoGridModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setModel(model)
        self.setItemDelegate(GridDelegate(self))
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setIconSize(QSize(_ICON, _ICON))
        self.setGridSize(QSize(_ICON + 24, _ICON + 36))
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setUniformItemSizes(True)
        self.setSpacing(8)
        self.setWordWrap(True)
        self.setSelectionMode(QListView.SelectionMode.ExtendedSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        rating = _RATING_KEYS.get(event.key())
        if rating is not None:
            self.rating_key.emit(rating)
            event.accept()
            return
        super().keyPressEvent(event)
