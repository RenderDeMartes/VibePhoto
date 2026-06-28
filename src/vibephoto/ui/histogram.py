"""RGB histogram widget for the Develop panel (professional).

Paints additive red/green/blue histograms of the current preview so overlapping
channels read white, the way the conventional histogram does. Updated on every render
from the engine's output buffer.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPolygonF
from PySide6.QtWidgets import QWidget

_CHANNEL_COLORS = (
    QColor(232, 86, 86, 150),
    QColor(96, 200, 112, 150),
    QColor(94, 142, 232, 150),
)


class HistogramWidget(QWidget):
    """Draws a 256-bin additive RGB histogram of the current image."""

    #: A channel counts as clipped when its share of pixels at 0 / 255 exceeds this.
    _CLIP_THRESHOLD = 0.001

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._hists: NDArray[np.float64] | None = None
        self._clip_low = np.zeros(3, dtype=np.float64)  # fraction clipped at black, per channel
        self._clip_high = np.zeros(3, dtype=np.float64)  # fraction clipped at white, per channel
        self.setMinimumHeight(96)
        self.setMaximumHeight(120)
        self.setToolTip("Histogram — corner triangles light up where shadows/highlights clip")

    def set_image(self, rgb: NDArray[np.uint8]) -> None:
        """Compute per-channel histograms from an ``(H, W, 3)`` uint8 image."""
        sample = rgb[::4, ::4].reshape(-1, rgb.shape[-1])
        hists = np.stack(
            [np.bincount(sample[:, c], minlength=256)[:256] for c in range(3)]
        ).astype(np.float64)
        total = max(1, sample.shape[0])
        self._clip_low = hists[:, 0] / total
        self._clip_high = hists[:, 255] / total
        peak = float(np.percentile(hists, 99.5)) or float(hists.max()) or 1.0
        self._hists = np.clip(hists / peak, 0.0, 1.0)
        self.update()

    def clear(self) -> None:
        self._hists = None
        self._clip_low = np.zeros(3, dtype=np.float64)
        self._clip_high = np.zeros(3, dtype=np.float64)
        self.update()

    def _clip_color(self, fractions: NDArray[np.float64]) -> QColor | None:
        """Indicator colour: white when every channel clips, else the clipped ones."""
        channels = [255 if f > self._CLIP_THRESHOLD else 0 for f in fractions]
        if not any(channels):
            return None
        return QColor(channels[0], channels[1], channels[2])

    def paintEvent(self, event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        painter.fillRect(self.rect(), QColor("#161719"))
        painter.setPen(QColor("#2a2d31"))
        for i in range(1, 4):  # quarter-tone gridlines
            x = round(width * i / 4)
            painter.drawLine(x, 0, x, height)
        if self._hists is None:
            return
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        painter.setPen(Qt.PenStyle.NoPen)
        for channel in range(3):
            polygon = QPolygonF([QPointF(0.0, float(height))])
            row = self._hists[channel]
            for x in range(256):
                polygon.append(QPointF(x / 255.0 * width, height - float(row[x]) * (height - 4)))
            polygon.append(QPointF(float(width), float(height)))
            painter.setBrush(_CHANNEL_COLORS[channel])
            painter.drawPolygon(polygon)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        self._draw_clip_indicators(painter, width)

    def _draw_clip_indicators(self, painter: QPainter, width: int) -> None:
        size = 8
        for fractions, x_outer, x_inner in (
            (self._clip_low, 0.0, float(size)),  # shadow clip, top-left
            (self._clip_high, float(width), float(width - size)),  # highlight clip, top-right
        ):
            colour = self._clip_color(fractions)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(colour if colour is not None else QColor("#3a3d42"))
            triangle = QPolygonF(
                [QPointF(x_outer, 0.0), QPointF(x_inner, 0.0), QPointF(x_outer, float(size))]
            )
            painter.drawPolygon(triangle)
