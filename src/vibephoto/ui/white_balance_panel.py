"""White Balance controls for RAW — Temperature (Kelvin) + Tint, like other professional editors.

Shown only when a RAW is open (its develop front-end is scene-linear, where a true
Kelvin white balance is meaningful). The Temp/Tint sliders drive the ``wb_kelvin`` /
``wb_tint`` fields via the panel's ``param_changed`` plumbing; the **Picker** arms
the canvas eyedropper, **As Shot** resets to the reference, and **Auto** asks the
host to estimate a neutral balance.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from vibephoto.processing.scene_linear import WB_REFERENCE_K

_TEMP_MIN, _TEMP_MAX = 2000, 50000


class WhiteBalancePanel(QWidget):
    """Kelvin Temperature + Tint sliders, an eyedropper, and As-Shot / Auto."""

    param_changed = Signal(object, object, float)  # param, subkey(None), value
    picker_toggled = Signal(bool)
    auto_requested = Signal()
    as_shot_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # The slider shows *true* Kelvin; the engine's wb_kelvin is anchored at the
        # 6500 reference, so we offset by (as-shot CCT - 6500) when converting.
        self._ref_kelvin = WB_REFERENCE_K
        self._temp = QSlider(Qt.Orientation.Horizontal)
        self._temp.setRange(_TEMP_MIN, _TEMP_MAX)
        self._temp.setSingleStep(50)
        self._temp.setValue(int(WB_REFERENCE_K))
        self._temp.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._temp_value = QLabel(f"{int(WB_REFERENCE_K)} K")
        self._temp.valueChanged.connect(self._on_temp)

        self._tint = QSlider(Qt.Orientation.Horizontal)
        self._tint.setRange(-100, 100)
        self._tint.setValue(0)
        self._tint.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._tint_value = QLabel("0")
        self._tint.valueChanged.connect(self._on_tint)

        grid = QGridLayout()
        grid.setContentsMargins(2, 2, 2, 2)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(2)
        grid.setColumnStretch(1, 1)
        self._add_row(grid, 0, "Temp", self._temp, self._temp_value)
        self._add_row(grid, 1, "Tint", self._tint, self._tint_value)

        self._picker = QToolButton()
        self._picker.setText("Picker")
        self._picker.setCheckable(True)
        self._picker.setToolTip("White Balance Selector — click a neutral grey in the photo")
        self._picker.toggled.connect(self.picker_toggled.emit)
        as_shot = QToolButton()
        as_shot.setText("As Shot")
        as_shot.setToolTip("Reset white balance to the camera's as-shot value")
        as_shot.clicked.connect(self.as_shot_requested.emit)
        auto = QToolButton()
        auto.setText("Auto")
        auto.setToolTip("Estimate a neutral white balance from the image")
        auto.clicked.connect(self.auto_requested.emit)
        for button in (self._picker, as_shot, auto):
            button.setAutoRaise(True)
            button.setStyleSheet(
                "QToolButton{color:#c9ccd1; padding:2px 8px; border:1px solid #3a3d42;"
                "border-radius:3px; font-size:11px;}"
                "QToolButton:hover{color:#fff;}"
                "QToolButton:checked{background:#2d6cdf; border-color:#2d6cdf; color:#fff;}"
            )
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(4)
        buttons.addWidget(self._picker)
        buttons.addWidget(as_shot)
        buttons.addWidget(auto)
        buttons.addStretch(1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(3)
        outer.addLayout(grid)
        outer.addLayout(buttons)

    def _add_row(
        self, grid: QGridLayout, row: int, name: str, slider: QSlider, value: QLabel
    ) -> None:
        label = QLabel(name)
        label.setStyleSheet("color:#c9ccd1; font-size:12px;")
        value.setStyleSheet("color:#9a9da3; font-size:12px;")
        value.setMinimumWidth(48)
        value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        grid.addWidget(label, row, 0)
        grid.addWidget(slider, row, 1)
        grid.addWidget(value, row, 2)

    def _on_temp(self, displayed: int) -> None:
        self._temp_value.setText(f"{displayed} K")
        # Convert the displayed (true) Kelvin back to the engine's anchored value.
        wb_kelvin = float(displayed) - self._ref_kelvin + WB_REFERENCE_K
        self.param_changed.emit("wb_kelvin", None, wb_kelvin)

    def _on_tint(self, value: int) -> None:
        self._tint_value.setText(str(value))
        self.param_changed.emit("wb_tint", None, float(value))

    def set_reference(self, ref_kelvin: float) -> None:
        """Calibrate the slider to a photo's as-shot Kelvin (so it reads true temp)."""
        self._ref_kelvin = ref_kelvin

    def set_values(self, kelvin: float, tint: float) -> None:
        """Sync the sliders without emitting (host pushes the engine's state in)."""
        displayed = round(kelvin - WB_REFERENCE_K + self._ref_kelvin)
        for slider, label, val, suffix in (
            (self._temp, self._temp_value, displayed, " K"),
            (self._tint, self._tint_value, round(tint), ""),
        ):
            slider.blockSignals(True)
            slider.setValue(val)
            label.setText(f"{val}{suffix}")
            slider.blockSignals(False)

    def set_picking(self, active: bool) -> None:
        """Reflect the canvas pick state on the Picker button (no signal)."""
        self._picker.blockSignals(True)
        self._picker.setChecked(active)
        self._picker.blockSignals(False)
