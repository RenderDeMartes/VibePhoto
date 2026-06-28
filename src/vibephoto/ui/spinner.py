"""A small indeterminate busy spinner for the status bar.

Paints a rotating arc while active (driven by a timer); hidden when idle. Used to
signal background work — a develop full render in flight, or a batch job running —
in the bottom corner of the window.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


class BusySpinner(QWidget):
    """A tiny rotating-arc spinner; call :meth:`set_active` to show/animate it."""

    def __init__(self, parent: QWidget | None = None, *, diameter: int = 16) -> None:
        super().__init__(parent)
        self._angle = 0
        self._diameter = diameter
        self.setFixedSize(diameter + 4, diameter + 4)
        self._timer = QTimer(self)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._advance)
        self.setVisible(False)
        self.setToolTip("Working…")

    def set_active(self, active: bool) -> None:
        if active == self._timer.isActive():
            return
        if active:
            self.setVisible(True)
            self._timer.start()
        else:
            self._timer.stop()
            self.setVisible(False)

    def _advance(self) -> None:
        self._angle = (self._angle + 30) % 360
        self.update()

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#3d8bfd"))
        pen.setWidth(2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        margin = 2
        rect = self.rect().adjusted(margin, margin, -margin, -margin)
        # A 270° arc rotated by the current angle (Qt angles are in 1/16°).
        painter.drawArc(rect, -self._angle * 16, 270 * 16)
