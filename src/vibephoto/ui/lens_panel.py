"""Lens-profile controls — auto-fix, brand/manual profiles, and custom profiles.

A big **Auto Fix** button (detects the lens from EXIF), plus a grouped profile picker
(Generic types, Canon and Sony lenses, a Manual entry, and the user's own saved
profiles) and Save/Delete so the manual Distortion / Defringe / Vignetting amounts can
be stored as a reusable profile. No per-camera measurement database is required.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vibephoto.processing.lens import LENS_PROFILE_GROUPS, MANUAL_PROFILE

Triple = tuple[float, float, float]


class LensProfilePanel(QWidget):
    """Auto-fix + a grouped lens-profile picker with user-saved profiles."""

    profile_chosen = Signal(str)  # a profile name (built-in or custom), or MANUAL_PROFILE
    auto_requested = Signal()
    save_requested = Signal(str)  # save current amounts under this name
    delete_requested = Signal(str)  # delete this custom profile

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._custom: dict[str, Triple] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(4)

        self._auto = QPushButton("Auto Fix Lens")
        self._auto.setCursor(Qt.CursorShape.PointingHandCursor)
        self._auto.setToolTip(
            "Detect the lens from the photo's metadata and apply the matching "
            "correction (specific Canon/Sony lens, fisheye, action-cam, or wide-angle)"
        )
        self._auto.setStyleSheet(
            "QPushButton{font-weight:600; color:#f0f0f0; background:#2d6cdf;"
            "border:none; border-radius:4px; padding:6px;}"
            "QPushButton:hover{background:#3d8bfd;}"
        )
        self._auto.clicked.connect(self.auto_requested.emit)
        layout.addWidget(self._auto)

        row = QHBoxLayout()
        label = QLabel("Profile")
        label.setStyleSheet("color:#c9ccd1; font-size:12px;")
        self._combo = QComboBox()
        self._combo.setToolTip("Apply a lens profile (or Manual to tune the sliders)")
        self._combo.activated.connect(self._on_activated)
        row.addWidget(label)
        row.addWidget(self._combo, 1)
        layout.addLayout(row)

        actions = QHBoxLayout()
        self._save = QPushButton("Save as…")
        self._save.setToolTip("Save the current Distortion / Defringe / Vignetting as a profile")
        self._save.clicked.connect(self._on_save)
        self._delete = QPushButton("Delete")
        self._delete.setToolTip("Delete the selected custom profile")
        self._delete.clicked.connect(self._on_delete)
        actions.addWidget(self._save)
        actions.addWidget(self._delete)
        layout.addLayout(actions)

        self._rebuild()

    # -- combo construction ------------------------------------------------- #

    def set_custom_profiles(self, custom: dict[str, Triple]) -> None:
        """Load the user's saved profiles and rebuild the picker."""
        self._custom = dict(custom)
        self._rebuild()

    def _add_header(self, text: str) -> None:
        """A non-selectable group header row in the combo."""
        self._combo.insertSeparator(self._combo.count())
        self._combo.addItem(text)
        model = self._combo.model()
        if isinstance(model, QStandardItemModel):
            model.item(self._combo.count() - 1).setEnabled(False)

    def _rebuild(self) -> None:
        self._combo.blockSignals(True)
        self._combo.clear()
        self._combo.addItem(MANUAL_PROFILE)
        for group, lenses in LENS_PROFILE_GROUPS:
            self._add_header(f"— {group} —")
            for name, *_vals in lenses:
                self._combo.addItem(name)
        if self._custom:
            self._add_header("— My Lenses —")
            for name in self._custom:
                self._combo.addItem(name)
        self._combo.blockSignals(False)
        self._update_delete_enabled()

    # -- interaction -------------------------------------------------------- #

    def _on_activated(self, index: int) -> None:
        name = self._combo.itemText(index)
        self._update_delete_enabled()
        self.profile_chosen.emit(name)

    def _on_save(self) -> None:
        name, ok = QInputDialog.getText(self, "Save Lens Profile", "Profile name:")
        if ok and name.strip():
            self.save_requested.emit(name.strip())

    def _on_delete(self) -> None:
        name = self._combo.currentText()
        if name in self._custom:
            self.delete_requested.emit(name)

    def _update_delete_enabled(self) -> None:
        self._delete.setEnabled(self._combo.currentText() in self._custom)

    def set_profile_name(self, name: str) -> None:
        """Reflect the active profile in the combo without emitting."""
        i = self._combo.findText(name)
        if i >= 0:
            self._combo.blockSignals(True)
            self._combo.setCurrentIndex(i)
            self._combo.blockSignals(False)
        self._update_delete_enabled()
