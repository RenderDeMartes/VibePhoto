"""The Develop tools footer — a compact action bar under the image canvas.

Groups, left to right: a star-rating control; composition overlays (picker +
opacity + rotate/flip); zoom out / label / zoom in; and Copy / Paste / Edit-Like-
Last. Small icon-glyph buttons with tooltips keep it tidy. It is a pure view — it
emits signals and the :class:`DevelopModule` does the work.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSlider,
    QToolButton,
    QWidget,
)

from vibephoto.ui.overlays import Overlay
from vibephoto.ui.star_rating import StarRating


def _tool_button(glyph: str, tooltip: str, *, checkable: bool = False) -> QToolButton:
    button = QToolButton()
    button.setText(glyph)
    button.setToolTip(tooltip)
    button.setCheckable(checkable)
    button.setAutoRaise(True)
    button.setFixedSize(28, 24)
    # Force an explicit point-size font: the symbol glyphs render too small via a
    # stylesheet font-size, but a real QFont resolves them crisply.
    font = QFont()
    font.setPointSize(13)
    button.setFont(font)
    # padding:0 is essential — the global theme pads QToolButton by 12px each
    # side, which would squash the glyph in this fixed-width button.
    button.setStyleSheet(
        "QToolButton{color:#c9ccd1; padding:0; border-radius:4px;}"
        "QToolButton:hover{color:#ffffff; background:#2f3236;}"
        "QToolButton:checked{color:#ffffff; background:#3d8bfd;}"
    )
    return button


def _text_button(label: str, tooltip: str) -> QToolButton:
    button = QToolButton()
    button.setText(label)
    button.setToolTip(tooltip)
    button.setAutoRaise(True)
    button.setStyleSheet(
        "QToolButton{font-size:11px; color:#c9ccd1; padding:2px 6px;}"
        "QToolButton:hover{color:#ffffff;}"
    )
    return button


def _separator() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.VLine)
    line.setStyleSheet("color:#3a3d42;")
    return line


class DevelopFooter(QWidget):
    """Ratings, composition overlays, zoom, and copy/paste/edit-like-last."""

    rating_changed = Signal(int)
    overlay_changed = Signal(object)  # Overlay
    overlay_opacity_changed = Signal(float)
    overlay_rotate_requested = Signal()
    overlay_flip_h_toggled = Signal(bool)
    overlay_flip_v_toggled = Signal(bool)
    zoom_in_requested = Signal()
    zoom_out_requested = Signal()
    copy_requested = Signal()
    paste_requested = Signal()
    edit_like_last_requested = Signal()
    crop_toggled = Signal(bool)
    rotate90_requested = Signal(int)  # +1 = CCW, -1 = CW quarter-turn
    straighten_changed = Signal(float)  # degrees, -45..45
    crop_reset_requested = Signal()  # back to the full frame, no rotation

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet("background:#1b1d20; border-top:1px solid #3a3d42;")
        self.setFixedHeight(34)

        self._stars = StarRating()
        self._stars.rating_changed.connect(self.rating_changed.emit)

        self._overlay = QComboBox()
        for overlay in Overlay:
            self._overlay.addItem(overlay.value, overlay)
        self._overlay.setToolTip("Composition overlay")
        self._overlay.currentIndexChanged.connect(self._on_overlay_changed)

        self._opacity = QSlider(Qt.Orientation.Horizontal)
        self._opacity.setRange(10, 100)
        self._opacity.setValue(50)
        self._opacity.setFixedWidth(70)
        self._opacity.setToolTip("Overlay opacity")
        self._opacity.valueChanged.connect(lambda v: self.overlay_opacity_changed.emit(v / 100.0))

        rotate = _tool_button("⟳", "Rotate overlay 90°")
        rotate.clicked.connect(self.overlay_rotate_requested.emit)
        flip_h = _tool_button("⇄", "Flip overlay horizontally", checkable=True)
        flip_h.toggled.connect(self.overlay_flip_h_toggled.emit)
        flip_v = _tool_button("⇅", "Flip overlay vertically", checkable=True)
        flip_v.toggled.connect(self.overlay_flip_v_toggled.emit)

        zoom_out = _tool_button("−", "Zoom out")  # noqa: RUF001 — U+2212 minus glyph
        zoom_out.clicked.connect(self.zoom_out_requested.emit)
        self._zoom_label = QLabel("Fit")
        self._zoom_label.setFixedWidth(44)
        self._zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._zoom_label.setStyleSheet("color:#9a9da3;")
        zoom_in = _tool_button("+", "Zoom in")
        zoom_in.clicked.connect(self.zoom_in_requested.emit)

        # Crop tool: a toggle, plus 90° rotate + straighten + reset controls shown only
        # while cropping (so the footer stays tidy the rest of the time). The free crop
        # itself is drag-on-canvas: drag a handle to resize to any aspect, drag inside
        # to move, drag outside the box to rotate.
        self._crop_btn = _tool_button(
            "⌗", "Crop & rotate (R / T to enter, V for mouse)", checkable=True
        )
        self._crop_btn.toggled.connect(self._on_crop_toggled)
        rot_ccw = _tool_button("⟲", "Rotate 90° counter-clockwise")
        rot_ccw.clicked.connect(lambda: self.rotate90_requested.emit(1))
        rot_cw = _tool_button("⟳", "Rotate 90° clockwise")
        rot_cw.clicked.connect(lambda: self.rotate90_requested.emit(-1))
        self._straighten = QSlider(Qt.Orientation.Horizontal)
        self._straighten.setRange(-450, 450)  # tenths of a degree
        self._straighten.setValue(0)
        self._straighten.setFixedWidth(90)
        self._straighten.setToolTip("Straighten (degrees)")
        self._straighten.valueChanged.connect(lambda v: self.straighten_changed.emit(v / 10.0))
        crop_reset = _text_button("Reset", "Reset crop to the full frame")
        crop_reset.clicked.connect(self.crop_reset_requested.emit)
        self._crop_controls = (rot_ccw, rot_cw, self._straighten, crop_reset)
        for widget in self._crop_controls:
            widget.setVisible(False)

        copy = _text_button("Copy", "Copy this photo's develop settings")
        copy.clicked.connect(self.copy_requested.emit)
        paste = _text_button("Paste", "Paste copied settings (Shift = all selected)")
        paste.clicked.connect(self.paste_requested.emit)
        like_last = _text_button(
            "Edit like last", "Apply the most recently edited photo's settings"
        )
        like_last.clicked.connect(self.edit_like_last_requested.emit)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(4)
        layout.addWidget(self._stars)
        layout.addWidget(_separator())
        layout.addWidget(self._crop_btn)
        layout.addWidget(rot_ccw)
        layout.addWidget(rot_cw)
        layout.addWidget(self._straighten)
        layout.addWidget(crop_reset)
        layout.addWidget(_separator())
        layout.addWidget(self._overlay)
        layout.addWidget(self._opacity)
        layout.addWidget(rotate)
        layout.addWidget(flip_h)
        layout.addWidget(flip_v)
        layout.addStretch(1)
        layout.addWidget(zoom_out)
        layout.addWidget(self._zoom_label)
        layout.addWidget(zoom_in)
        layout.addWidget(_separator())
        layout.addWidget(copy)
        layout.addWidget(paste)
        layout.addWidget(like_last)

    def _on_overlay_changed(self, index: int) -> None:
        self.overlay_changed.emit(self._overlay.itemData(index))

    def _on_crop_toggled(self, active: bool) -> None:
        for widget in self._crop_controls:
            widget.setVisible(active)
        self.crop_toggled.emit(active)

    def set_straighten(self, degrees: float) -> None:
        """Sync the straighten slider to the current geometry (no emit)."""
        self._straighten.blockSignals(True)
        self._straighten.setValue(round(degrees * 10))
        self._straighten.blockSignals(False)

    @property
    def crop_active(self) -> bool:
        return self._crop_btn.isChecked()

    def set_crop_active(self, active: bool) -> None:
        """Enter/leave crop from a shortcut (R/T enter, V exits); no-op if unchanged."""
        if self._crop_btn.isChecked() != active:
            self._crop_btn.setChecked(active)  # toggled → _on_crop_toggled fires

    def set_rating(self, rating: int) -> None:
        self._stars.set_rating(rating)

    def set_zoom_label(self, zoom: float) -> None:
        label = "Fit" if abs(zoom - 1.0) < 0.01 else f"{zoom:.1f}×"  # noqa: RUF001 — U+00D7
        self._zoom_label.setText(label)
