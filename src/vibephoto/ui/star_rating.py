"""A compact 5-star rating control.

Paints five stars that fill up to the hovered position, so a single click sets a
rating (1-5); clicking the current rating again clears it (toggle to 0). Emits
:attr:`rating_changed`. Used in the Develop tools footer.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPolygonF
from PySide6.QtWidgets import QWidget

_STAR = 18
_GAP = 3
_FILLED = QColor("#ffce47")
_EMPTY = QColor("#5a5e64")
_HOVER = QColor("#ffe08a")


def _star_polygon(cx: float, cy: float, radius: float) -> QPolygonF:
    points = []
    for i in range(10):
        angle = math.pi / 2 + i * math.pi / 5
        r = radius if i % 2 == 0 else radius * 0.42
        points.append(QPointF(cx + r * math.cos(angle), cy - r * math.sin(angle)))
    return QPolygonF(points)


class StarRating(QWidget):
    """Five clickable stars; click sets 1-5, click-again on the same star clears."""

    rating_changed = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rating = 0
        self._hover = 0
        self.setMouseTracking(True)
        self.setFixedSize(5 * _STAR + 4 * _GAP, _STAR)
        self.setToolTip("Rate this photo (click a star; 1-5 also work on the grid)")

    def set_rating(self, rating: int) -> None:
        self._rating = max(0, min(5, rating))
        self.update()

    def _star_at(self, x: float) -> int:
        index = int(x // (_STAR + _GAP)) + 1
        return max(0, min(5, index))

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self._hover = self._star_at(event.position().x())
        self.update()

    def leaveEvent(self, event: object) -> None:
        self._hover = 0
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        clicked = self._star_at(event.position().x())
        new = 0 if clicked == self._rating else clicked
        self._rating = new
        self.update()
        self.rating_changed.emit(new)

    def paintEvent(self, event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        active = self._hover or self._rating
        for i in range(5):
            cx = i * (_STAR + _GAP) + _STAR / 2
            colour = (_HOVER if self._hover else _FILLED) if i < active else _EMPTY
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(colour)
            painter.drawPolygon(_star_polygon(cx, _STAR / 2, _STAR / 2 - 1))

    def sizeHint(self) -> QSize:
        return QSize(5 * _STAR + 4 * _GAP, _STAR)
