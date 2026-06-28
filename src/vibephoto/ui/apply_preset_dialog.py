"""Dialog to apply a preset to a batch of photos, choosing the layer mode.

Pick a preset (grouped by folder) and whether to add it **on a new layer** (stacked
over each photo's existing edits) or **on the same layer** (replacing the base edit).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

Groups = list[tuple[str, list[tuple[str, Path]]]]


class ApplyPresetDialog(QDialog):
    """Collects a preset choice + layer mode for a batch apply."""

    def __init__(self, groups: Groups, count: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Apply Preset")
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        heading = QLabel(f"Apply a preset to {count} photo{'s' if count != 1 else ''}")
        heading.setStyleSheet("font-size:14px; font-weight:600; padding-bottom:4px;")
        layout.addWidget(heading)

        self._combo = QComboBox()
        self._populate(groups)
        layout.addWidget(self._combo)

        layout.addWidget(QLabel("Apply as:"))
        self._new_layer = QRadioButton("A new layer (keep existing edits underneath)")
        self._same_layer = QRadioButton("The same layer (replace existing edits)")
        self._new_layer.setChecked(True)
        layout.addWidget(self._new_layer)
        layout.addWidget(self._same_layer)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(f"Apply to {count}")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _populate(self, groups: Groups) -> None:
        model = self._combo.model()
        for group, presets in groups:
            if not presets:
                continue
            self._combo.addItem(f"— {group} —")
            if isinstance(model, QStandardItemModel):
                model.item(self._combo.count() - 1).setEnabled(False)  # header
            for name, path in presets:
                self._combo.addItem(name, str(path))
        # Select the first real (enabled) entry.
        for i in range(self._combo.count()):
            if self._combo.itemData(i):
                self._combo.setCurrentIndex(i)
                break

    def chosen_preset(self) -> Path | None:
        data = self._combo.currentData()
        return Path(data) if data else None

    def mode(self) -> str:
        return "new" if self._new_layer.isChecked() else "same"
