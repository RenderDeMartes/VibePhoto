"""Interactive tone-curve editor — a draggable point curve like the conventional.

Edits a master (RGB) curve plus per-channel R/G/B curves, each a list of control
points in 0..255 that map straight onto ``EditState.curve_*`` and the renderer's
``point_curves`` op. The op interpolates points linearly, so the drawn curve is
WYSIWYG. Click an empty spot to add a point, drag to move, right-click a point to
delete it (the two end points stay). Emits :attr:`curve_changed(field, points)`
for the active channel; an untouched channel reports ``[]`` (identity).
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vibephoto.processing.edit_state import EditState

#: (button label, EditState field, curve colour)
_CHANNELS = (
    ("RGB", "curve_rgb", "#d6d8dc"),
    ("R", "curve_red", "#ff6b6b"),
    ("G", "curve_green", "#69db7c"),
    ("B", "curve_blue", "#4dabf7"),
)
_IDENTITY: list[tuple[int, int]] = [(0, 0), (255, 255)]
_PAD = 6
_HIT = 11  # px radius to grab an existing point


class _CurveCanvas(QWidget):
    """The plot area: grid, identity diagonal, the curve, and its points."""

    changed = Signal()  # the active channel's points changed

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(200, 200)
        self.setMouseTracking(True)
        self._channel = 0
        self._points: list[list[tuple[int, int]]] = [list(_IDENTITY) for _ in _CHANNELS]
        self._drag: int | None = None

    # -- public ------------------------------------------------------------ #

    @property
    def field(self) -> str:
        return _CHANNELS[self._channel][1]

    def active_points(self) -> list[tuple[int, int]]:
        """The active channel's points, or ``[]`` when it is still identity."""
        pts = self._points[self._channel]
        return [] if pts == _IDENTITY else [(int(x), int(y)) for x, y in pts]

    def set_channel(self, index: int) -> None:
        self._channel = index
        self._drag = None
        self.update()

    def set_from_state(self, state: EditState) -> None:
        for i, (_, field, _) in enumerate(_CHANNELS):
            pts = getattr(state, field)
            self._points[i] = [(int(x), int(y)) for x, y in pts] if pts else list(_IDENTITY)
        self._drag = None
        self.update()

    # -- geometry ---------------------------------------------------------- #

    def _plot(self) -> QRectF:
        return QRectF(
            _PAD, _PAD, max(1, self.width() - 2 * _PAD), max(1, self.height() - 2 * _PAD)
        )

    def _to_px(self, x: int, y: int) -> QPointF:
        rect = self._plot()
        return QPointF(
            rect.left() + rect.width() * (x / 255.0),
            rect.bottom() - rect.height() * (y / 255.0),
        )

    def _to_data(self, px: float, py: float) -> tuple[int, int]:
        rect = self._plot()
        x = (px - rect.left()) / rect.width() * 255.0
        y = (rect.bottom() - py) / rect.height() * 255.0
        return round(max(0.0, min(255.0, x))), round(max(0.0, min(255.0, y)))

    def _point_at(self, px: float, py: float) -> int | None:
        for i, (x, y) in enumerate(self._points[self._channel]):
            handle = self._to_px(x, y)
            if (handle.x() - px) ** 2 + (handle.y() - py) ** 2 <= _HIT * _HIT:
                return i
        return None

    # -- editing ----------------------------------------------------------- #

    def mousePressEvent(self, event: QMouseEvent) -> None:
        px, py = event.position().x(), event.position().y()
        if event.button() == Qt.MouseButton.RightButton:
            self._remove_point(px, py)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        hit = self._point_at(px, py)
        if hit is None:
            hit = self._add_point(px, py)
        self._drag = hit

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag is None:
            return
        x, y = self._to_data(event.position().x(), event.position().y())
        pts = self._points[self._channel]
        last = len(pts) - 1
        if self._drag == 0:
            x = 0  # end points keep their x, move only in y
        elif self._drag == last:
            x = 255
        else:  # keep interior points strictly ordered between their neighbours
            x = max(pts[self._drag - 1][0] + 1, min(pts[self._drag + 1][0] - 1, x))
        pts[self._drag] = (x, y)
        self.update()
        self.changed.emit()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag = None

    def _add_point(self, px: float, py: float) -> int:
        x, y = self._to_data(px, py)
        pts = self._points[self._channel]
        x = max(1, min(254, x))
        index = next((i for i, p in enumerate(pts) if p[0] > x), len(pts))
        pts.insert(index, (x, y))
        self.changed.emit()
        return index

    def _remove_point(self, px: float, py: float) -> None:
        hit = self._point_at(px, py)
        pts = self._points[self._channel]
        if hit is not None and 0 < hit < len(pts) - 1:  # never the end points
            del pts[hit]
            self.update()
            self.changed.emit()

    # -- painting ---------------------------------------------------------- #

    def paintEvent(self, event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self._plot()
        painter.fillRect(rect, QColor("#16181b"))
        painter.setPen(QPen(QColor("#2c2f33"), 1))
        for t in (1 / 4, 2 / 4, 3 / 4):
            x = rect.left() + rect.width() * t
            y = rect.top() + rect.height() * t
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        painter.setPen(QPen(QColor("#3a3d42"), 1, Qt.PenStyle.DashLine))
        painter.drawLine(rect.bottomLeft(), rect.topRight())  # identity reference

        colour = QColor(_CHANNELS[self._channel][2])
        pts = self._points[self._channel]
        painter.setPen(QPen(colour, 2))
        painter.drawPolyline(QPolygonF([self._to_px(x, y) for x, y in pts]))
        painter.setBrush(colour)
        painter.setPen(QPen(QColor("#101113"), 1))
        for x, y in pts:
            painter.drawEllipse(self._to_px(x, y), 4, 4)


class ToneCurveEditor(QWidget):
    """Channel selector (RGB/R/G/B) above the draggable curve canvas."""

    curve_changed = Signal(str, object)  # EditState field, list[(int, int)]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._canvas = _CurveCanvas()
        self._canvas.changed.connect(self._emit)

        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(3)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for index, (label, _field, colour) in enumerate(_CHANNELS):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setFixedHeight(20)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(
                "QPushButton{color:#9a9da3; background:#202225; border:1px solid #3a3d42;"
                "font-size:11px; padding:1px 8px;}"
                f"QPushButton:checked{{color:#101113; background:{colour}; border-color:{colour};}}"
            )
            self._group.addButton(button, index)
            bar.addWidget(button)
        bar.addStretch(1)
        self._group.button(0).setChecked(True)
        self._group.idClicked.connect(self._canvas.set_channel)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(3)
        outer.addLayout(bar)
        outer.addWidget(self._canvas)

    def _emit(self) -> None:
        self.curve_changed.emit(self._canvas.field, self._canvas.active_points())

    def set_state(self, state: EditState) -> None:
        self._canvas.set_from_state(state)
