"""Color-grading wheels — professional 3-way (+ global) colour grading.

Four hue/saturation wheels (Shadows, Midtones, Highlights, Global) plus luminance,
balance, and blending sliders, mapped onto the ``grade_*`` fields of
:class:`EditState`. Each wheel sets a zone's hue (angle) and saturation (radius);
dragging the centre dot outward tints that tonal zone. The panel is a pure view —
it emits :attr:`param_changed` (``param, None, value``) so the host can route it
through the same slot the sliders use.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from vibephoto.processing.edit_state import EditState

_WHEEL_D = 104  # wheel diameter in px


def _hsv_to_rgb(h: np.ndarray, s: np.ndarray, v: float) -> np.ndarray:
    """Vectorised HSV→RGB (hue in degrees, sat 0..1, value scalar) → uint8 RGB."""
    h6 = (h / 60.0) % 6.0
    i = np.floor(h6).astype(np.int32)
    f = h6 - i
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))
    v_arr = np.full_like(s, v)
    r = np.select([i == 0, i == 1, i == 2, i == 3, i == 4, i == 5], [v_arr, q, p, p, t, v_arr])
    g = np.select([i == 0, i == 1, i == 2, i == 3, i == 4, i == 5], [t, v_arr, v_arr, q, p, p])
    b = np.select([i == 0, i == 1, i == 2, i == 3, i == 4, i == 5], [p, p, t, v_arr, v_arr, q])
    return (np.stack([r, g, b], axis=-1) * 255.0).astype(np.uint8)


def _wheel_image(diameter: int) -> QImage:
    """Build a hue(angle)/saturation(radius) colour-wheel as an RGBA QImage."""
    yy, xx = np.mgrid[0:diameter, 0:diameter]
    centre = (diameter - 1) / 2.0
    dx = (xx - centre) / centre
    dy = (yy - centre) / centre
    radius = np.sqrt(dx * dx + dy * dy)
    hue = np.degrees(np.arctan2(-dy, dx)) % 360.0
    sat = np.clip(radius, 0.0, 1.0)
    rgb = _hsv_to_rgb(hue, sat, 1.0)
    alpha = np.clip((1.0 - radius) * diameter * 0.5, 0.0, 1.0)  # 1px feathered edge
    alpha = np.where(radius <= 1.0, np.clip(alpha + (radius <= 0.97), 0.0, 1.0), 0.0)
    rgba = np.dstack([rgb, (alpha * 255.0).astype(np.uint8)])
    rgba = np.ascontiguousarray(rgba)
    image = QImage(rgba.data, diameter, diameter, 4 * diameter, QImage.Format.Format_RGBA8888)
    return image.copy()


class ColorWheel(QWidget):
    """A hue/saturation wheel with a draggable handle. Emits ``changed(hue, sat)``."""

    changed = Signal(float, float)  # hue 0..360, sat 0..100

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._title = title
        self._hue = 0.0
        self._sat = 0.0  # 0..1 internally
        self._image = _wheel_image(_WHEEL_D)
        self.setFixedSize(_WHEEL_D + 4, _WHEEL_D + 18)
        self.setToolTip(f"{title}: drag from centre to tint; angle = hue, distance = strength")

    def set_values(self, hue: float, sat: float) -> None:
        """Set without emitting (sat given 0..100)."""
        self._hue = hue % 360.0
        self._sat = max(0.0, min(1.0, sat / 100.0))
        self.update()

    def _centre(self) -> QPointF:
        return QPointF(self.width() / 2.0, _WHEEL_D / 2.0 + 1)

    def _apply_pos(self, x: float, y: float) -> None:
        centre = self._centre()
        dx = x - centre.x()
        dy = y - centre.y()
        radius = (dx * dx + dy * dy) ** 0.5
        max_r = _WHEEL_D / 2.0
        self._sat = max(0.0, min(1.0, radius / max_r))
        if radius > 1.0:
            self._hue = float(np.degrees(np.arctan2(-dy, dx)) % 360.0)
        self.update()
        self.changed.emit(self._hue, self._sat * 100.0)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._apply_pos(event.position().x(), event.position().y())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._apply_pos(event.position().x(), event.position().y())

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        self._sat = 0.0  # reset this zone to neutral
        self.update()
        self.changed.emit(self._hue, 0.0)

    def paintEvent(self, event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.drawImage(QPointF(2, 1), self._image)
        centre = self._centre()
        painter.setPen(QPen(QColor("#26282b"), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(centre, _WHEEL_D / 2.0, _WHEEL_D / 2.0)
        # handle
        angle = np.radians(self._hue)
        hx = centre.x() + self._sat * (_WHEEL_D / 2.0) * float(np.cos(angle))
        hy = centre.y() - self._sat * (_WHEEL_D / 2.0) * float(np.sin(angle))
        painter.setPen(QPen(QColor("#101113"), 2))
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(QPointF(hx, hy), 5, 5)
        painter.setPen(QColor("#9a9da3"))
        painter.drawText(
            0, _WHEEL_D + 2, self.width(), 16, Qt.AlignmentFlag.AlignCenter, self._title
        )

    def sizeHint(self) -> QSize:
        return QSize(_WHEEL_D + 4, _WHEEL_D + 18)


def _mini_slider(minimum: int, maximum: int, value: int, tooltip: str) -> QSlider:
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setRange(minimum, maximum)
    slider.setValue(value)
    slider.setToolTip(tooltip)
    slider.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
    return slider


class ColorGradingPanel(QWidget):
    """Three-way + global colour wheels with luminance, balance, and blending."""

    param_changed = Signal(object, object, float)  # param, subkey(None), value

    #: (label, field-prefix, has-luminance)
    _ZONES = (
        ("Shadows", "grade_shadow", True),
        ("Midtones", "grade_mid", True),
        ("Highlights", "grade_highlight", True),
        ("Global", "grade_global", False),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._wheels: dict[str, ColorWheel] = {}
        self._lum: dict[str, QSlider] = {}

        grid = QGridLayout()
        grid.setContentsMargins(0, 2, 0, 2)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(2)
        for index, (label, prefix, has_lum) in enumerate(self._ZONES):
            row, col = divmod(index, 2)
            cell = QVBoxLayout()
            cell.setSpacing(1)
            wheel = ColorWheel(label)
            wheel.changed.connect(lambda h, s, p=prefix: self._on_wheel(p, h, s))
            self._wheels[prefix] = wheel
            cell.addWidget(wheel, 0, Qt.AlignmentFlag.AlignHCenter)
            if has_lum:
                lum = _mini_slider(-100, 100, 0, f"{label} luminance")
                lum.valueChanged.connect(
                    lambda v, p=prefix: self.param_changed.emit(f"{p}_lum", None, float(v))
                )
                self._lum[prefix] = lum
                cell.addWidget(lum)
            holder = QWidget()
            holder.setLayout(cell)
            grid.addWidget(holder, row, col)

        self._balance = _mini_slider(-100, 100, 0, "Balance (shadow ↔ highlight split)")
        self._balance.valueChanged.connect(
            lambda v: self.param_changed.emit("grade_balance", None, float(v))
        )
        self._blending = _mini_slider(0, 100, 50, "Blending (zone overlap)")
        self._blending.valueChanged.connect(
            lambda v: self.param_changed.emit("grade_blending", None, float(v))
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(2, 2, 2, 2)
        outer.setSpacing(2)
        outer.addLayout(grid)
        outer.addWidget(self._labelled("Balance", self._balance))
        outer.addWidget(self._labelled("Blending", self._blending))

    def _labelled(self, text: str, slider: QSlider) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        label = QLabel(text)
        label.setStyleSheet("color:#9a9da3; font-size:11px;")
        layout.addWidget(label)
        layout.addWidget(slider)
        return box

    def _on_wheel(self, prefix: str, hue: float, sat: float) -> None:
        self.param_changed.emit(f"{prefix}_hue", None, hue)
        self.param_changed.emit(f"{prefix}_sat", None, sat)

    def set_state(self, state: EditState) -> None:
        """Sync every wheel/slider to ``state`` without emitting."""
        for prefix, wheel in self._wheels.items():
            wheel.set_values(getattr(state, f"{prefix}_hue"), getattr(state, f"{prefix}_sat"))
        for prefix, slider in self._lum.items():
            _set_slider(slider, getattr(state, f"{prefix}_lum"))
        _set_slider(self._balance, state.grade_balance)
        _set_slider(self._blending, state.grade_blending)


def _set_slider(slider: QSlider, value: float) -> None:
    slider.blockSignals(True)
    slider.setValue(round(value))
    slider.blockSignals(False)
