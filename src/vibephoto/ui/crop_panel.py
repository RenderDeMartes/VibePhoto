"""Crop & Straighten panel — photo-level geometry controls.

A compact, overlay-free crop: a straighten slider plus centred aspect-ratio
presets (the rectangle is computed from the image's own aspect, so "4:5" frames a
centred 4:5 region). Emits a :class:`~vibephoto.processing.geometry.Geometry`; the
Develop module applies it to the photo's base before the layer stack develops it.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from vibephoto.processing.geometry import Geometry

#: Aspect presets (label, width:height or None for the full frame).
_ASPECTS: tuple[tuple[str, float | None], ...] = (
    ("Original", None),
    ("1:1", 1.0),
    ("4:5", 4 / 5),
    ("5:4", 5 / 4),
    ("3:2", 3 / 2),
    ("2:3", 2 / 3),
    ("16:9", 16 / 9),
)


def centered_crop(image_aspect: float, target: float | None) -> tuple[float, float, float, float]:
    """Normalised (left, top, right, bottom) for a centred ``target`` aspect crop.

    ``image_aspect`` and ``target`` are width/height. ``None`` = the whole frame.
    """
    if target is None or image_aspect <= 0:
        return (0.0, 0.0, 1.0, 1.0)
    if target >= image_aspect:
        frac = image_aspect / target  # limited by width → inset top/bottom
        inset = (1.0 - frac) / 2.0
        return (0.0, inset, 1.0, inset + frac)
    frac = target / image_aspect  # limited by height → inset left/right
    inset = (1.0 - frac) / 2.0
    return (inset, 0.0, inset + frac, 1.0)


class CropPanel(QWidget):
    """Straighten slider + aspect-ratio presets, emitting a :class:`Geometry`."""

    geometry_changed = Signal(object)  # Geometry

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._image_aspect = 1.0
        self._geometry = Geometry()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(4)

        grid = QGridLayout()
        grid.setColumnStretch(0, 0)
        for col, (label, target) in enumerate(_ASPECTS):
            button = QPushButton(label)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(
                "QPushButton{color:#c9ccd1; background:#202225; border:1px solid #3a3d42;"
                "padding:3px 6px; font-size:11px;}"
                "QPushButton:hover{border-color:#2d6cdf;}"
            )
            button.clicked.connect(lambda _=False, t=target: self._set_aspect(t))
            grid.addWidget(button, col // 4, col % 4)
        layout.addLayout(grid)

        row = QHBoxLayout()
        name = QLabel("Straighten")
        name.setStyleSheet("color:#c9ccd1; font-size:12px;")
        self._angle_value = QLabel("0°")
        self._angle_value.setStyleSheet("color:#9a9da3; font-size:12px;")
        self._angle = QSlider(Qt.Orientation.Horizontal)
        self._angle.setMinimum(-450)  # tenths of a degree, ±45°
        self._angle.setMaximum(450)
        self._angle.setValue(0)
        self._angle.valueChanged.connect(self._on_angle)
        row.addWidget(name)
        row.addWidget(self._angle, 1)
        row.addWidget(self._angle_value)
        layout.addLayout(row)

        reset = QPushButton("Reset Crop")
        reset.setCursor(Qt.CursorShape.PointingHandCursor)
        reset.clicked.connect(self._reset)
        layout.addWidget(reset)

    # -- external state ----------------------------------------------------- #

    def set_image_aspect(self, aspect: float) -> None:
        """Tell the panel the base image's width/height, so aspect crops are correct."""
        self._image_aspect = aspect if aspect > 0 else 1.0

    def set_geometry(self, geometry: Geometry) -> None:
        """Sync the controls to an existing geometry without re-emitting."""
        self._geometry = geometry.copy()
        self._angle.blockSignals(True)
        self._angle.setValue(round(geometry.angle * 10))
        self._angle.blockSignals(False)
        self._angle_value.setText(f"{geometry.angle:.1f}°")

    # -- interaction -------------------------------------------------------- #

    def _set_aspect(self, target: float | None) -> None:
        left, top, right, bottom = centered_crop(self._image_aspect, target)
        self._geometry.left, self._geometry.top = left, top
        self._geometry.right, self._geometry.bottom = right, bottom
        self.geometry_changed.emit(self._geometry.copy())

    def _on_angle(self, raw: int) -> None:
        self._geometry.angle = raw / 10.0
        self._angle_value.setText(f"{self._geometry.angle:.1f}°")
        self.geometry_changed.emit(self._geometry.copy())

    def _reset(self) -> None:
        self._geometry = Geometry()
        self.set_geometry(self._geometry)
        self.geometry_changed.emit(self._geometry.copy())
