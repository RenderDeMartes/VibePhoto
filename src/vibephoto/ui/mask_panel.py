"""Masks panel — add and tune per-layer local-adjustment masks.

Panel-driven (no canvas drawing yet): add a radial or graduated (linear) mask to
the active layer and tune its position, size, and feather with sliders, plus
invert / subtract. The active layer's edit then applies only inside the combined
mask. Brush and object/subject-select masks will arrive with the canvas tools.

Emits the updated mask list; the Develop module stores it on the active layer and
re-renders.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from vibephoto.processing.mask import Mask


def _slider(minimum: int, maximum: int, value: int) -> QSlider:
    s = QSlider(Qt.Orientation.Horizontal)
    s.setMinimum(minimum)
    s.setMaximum(maximum)
    s.setValue(value)
    return s


def _row(label: str, widget: QWidget) -> QWidget:
    box = QHBoxLayout()
    box.setContentsMargins(0, 0, 0, 0)
    name = QLabel(label)
    name.setStyleSheet("color:#c9ccd1; font-size:12px;")
    name.setMinimumWidth(64)
    box.addWidget(name)
    box.addWidget(widget, 1)
    holder = QWidget()
    holder.setLayout(box)
    return holder


class MaskPanel(QWidget):
    """Manage the active layer's masks (add / select / tune / delete)."""

    masks_changed = Signal(object)  # list[Mask]
    mask_selected = Signal(object)  # the Mask to edit on the canvas, or None

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._masks: list[Mask] = []
        self._syncing = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(4)

        add = QHBoxLayout()
        radial_btn = QPushButton("+ Radial")
        grad_btn = QPushButton("+ Gradient")
        brush_btn = QPushButton("+ Brush")
        radial_btn.clicked.connect(lambda: self._add(Mask.radial()))
        grad_btn.clicked.connect(lambda: self._add(Mask.gradient()))
        brush_btn.clicked.connect(lambda: self._add(Mask.brush()))
        for button in (radial_btn, grad_btn, brush_btn):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            add.addWidget(button)
        layout.addLayout(add)

        self._list = QListWidget()
        self._list.setMaximumHeight(96)
        self._list.currentRowChanged.connect(self._on_select)
        layout.addWidget(self._list)

        self._edit_on_canvas = QCheckBox("Edit on canvas")
        self._edit_on_canvas.setChecked(True)
        self._edit_on_canvas.setStyleSheet("color:#c9ccd1; font-size:11px;")
        self._edit_on_canvas.toggled.connect(self._emit_selection)
        layout.addWidget(self._edit_on_canvas)

        self._hint = QLabel("No masks — this layer applies globally.")
        self._hint.setStyleSheet("color:#8a8d93; font-size:11px;")
        self._hint.setWordWrap(True)
        layout.addWidget(self._hint)

        # Shared geometry controls (relabelled per kind).
        self._axis = QComboBox()
        self._axis.addItems(["Vertical", "Horizontal"])
        self._axis.currentIndexChanged.connect(self._on_param)
        self._axis_row = _row("Direction", self._axis)
        self._a = _slider(0, 100, 50)  # cx  / start
        self._b = _slider(0, 100, 50)  # cy  / end
        self._size = _slider(2, 100, 30)  # radial size
        self._feather = _slider(1, 100, 50)
        for s in (self._a, self._b, self._size, self._feather):
            s.valueChanged.connect(self._on_param)
        self._a_row = _row("Center X", self._a)
        self._b_row = _row("Center Y", self._b)
        self._size_row = _row("Size", self._size)
        self._feather_row = _row("Feather", self._feather)
        for w in (self._axis_row, self._a_row, self._b_row, self._size_row, self._feather_row):
            layout.addWidget(w)

        flags = QHBoxLayout()
        self._invert = QCheckBox("Invert")
        self._subtract = QCheckBox("Subtract")
        for box in (self._invert, self._subtract):
            box.setStyleSheet("color:#c9ccd1; font-size:11px;")
            box.toggled.connect(self._on_param)
            flags.addWidget(box)
        self._delete = QPushButton("Delete")
        self._delete.clicked.connect(self._on_delete)
        flags.addWidget(self._delete)
        layout.addLayout(flags)

        self._refresh_list()
        self._show_controls(None)

    # -- external state ----------------------------------------------------- #

    def set_masks(self, masks: list[Mask]) -> None:
        """Load the active layer's masks (without emitting)."""
        self._masks = [m.copy() for m in masks]
        self._refresh_list()
        row = 0 if self._masks else -1
        self._list.setCurrentRow(row)
        self._show_controls(self._current())

    # -- helpers ------------------------------------------------------------ #

    def _current(self) -> Mask | None:
        row = self._list.currentRow()
        return self._masks[row] if 0 <= row < len(self._masks) else None

    def _add(self, mask: Mask) -> None:
        self._masks.append(mask)
        self._refresh_list()
        self._list.setCurrentRow(len(self._masks) - 1)
        self._emit()

    def _on_delete(self) -> None:
        row = self._list.currentRow()
        if 0 <= row < len(self._masks):
            del self._masks[row]
            self._refresh_list()
            self._list.setCurrentRow(min(row, len(self._masks) - 1))
            self._emit()

    def _on_select(self, _row: int) -> None:
        self._show_controls(self._current())
        self._emit_selection()

    def _emit_selection(self, *_args: object) -> None:
        """Tell the canvas which mask to edit (or None when editing is off)."""
        if self._syncing:
            return
        mask = self._current() if self._edit_on_canvas.isChecked() else None
        self.mask_selected.emit(mask.copy() if mask is not None else None)

    def current_index(self) -> int:
        return self._list.currentRow()

    def selected_mask(self) -> Mask | None:
        """The mask the canvas should edit (selected + editing on), else None."""
        mask = self._current()
        if mask is None or not self._edit_on_canvas.isChecked():
            return None
        return mask.copy()

    def update_current(self, mask: Mask) -> None:
        """Replace the selected mask from a canvas edit, syncing sliders (no re-emit).

        Only geometry changes arrive here (handle drag / brush paint), so the list
        label is unchanged — skip the list refresh to avoid disturbing the selection
        (and the canvas edit) mid-drag.
        """
        row = self._list.currentRow()
        if not 0 <= row < len(self._masks):
            return
        self._masks[row] = mask.copy()
        self._show_controls(self._masks[row])

    def _refresh_list(self) -> None:
        self._syncing = True
        self._list.clear()
        for i, mask in enumerate(self._masks, start=1):
            kind = "Radial" if mask.kind == "radial" else "Gradient"
            tags = " inv" * mask.invert + " sub" * mask.subtract
            self._list.addItem(f"{kind} {i}{tags}")
        self._syncing = False
        self._hint.setVisible(not self._masks)

    def _show_controls(self, mask: Mask | None) -> None:
        """Reveal + populate the controls for the selected mask's kind."""
        has = mask is not None
        for w in (self._feather_row, self._invert, self._subtract, self._delete):
            w.setVisible(has)
        is_radial = has and mask is not None and mask.kind == "radial"
        is_grad = has and mask is not None and mask.kind == "linear"
        self._a_row.setVisible(is_radial)
        self._b_row.setVisible(is_radial)
        self._size_row.setVisible(is_radial)
        self._axis_row.setVisible(is_grad)
        if not has or mask is None:
            return
        self._syncing = True
        p = mask.params
        if is_radial:
            self._a.setValue(int(float(p.get("cx", 0.5)) * 100))
            self._b.setValue(int(float(p.get("cy", 0.5)) * 100))
            self._size.setValue(int(float(p.get("rx", 0.3)) * 100))
        else:
            horizontal = p.get("y0", 0.5) == p.get("y1", 0.5) and p.get("x0") != p.get("x1")
            self._axis.setCurrentIndex(1 if horizontal else 0)
            start = p.get("x0", 0.0) if horizontal else p.get("y0", 0.0)
            end = p.get("x1", 0.4) if horizontal else p.get("y1", 0.4)
            self._a.setValue(int(float(start) * 100))
            self._b.setValue(int(float(end) * 100))
        self._feather.setValue(int(mask.feather * 100))
        self._invert.setChecked(mask.invert)
        self._subtract.setChecked(mask.subtract)
        self._syncing = False

    def _on_param(self, *_args: object) -> None:
        if self._syncing:
            return
        mask = self._current()
        if mask is None:
            return
        mask.feather = self._feather.value() / 100.0
        mask.invert = self._invert.isChecked()
        mask.subtract = self._subtract.isChecked()
        if mask.kind == "radial":
            size = self._size.value() / 100.0
            mask.params = {
                "cx": self._a.value() / 100.0,
                "cy": self._b.value() / 100.0,
                "rx": size,
                "ry": size,
            }
        else:
            axis = "horizontal" if self._axis.currentIndex() == 1 else "vertical"
            updated = Mask.gradient(axis, self._a.value() / 100.0, self._b.value() / 100.0)
            mask.params = updated.params
        self._refresh_list()
        self._emit()

    def _emit(self) -> None:
        self.masks_changed.emit([m.copy() for m in self._masks])
