"""Export dialog — choose an export preset, destination, and optional watermark.

Thin UI over :data:`BUILTIN_EXPORT_PRESETS`; it returns the resolved
:class:`ExportPreset` (with any watermark applied) and destination so the caller
can run the batch off the GUI thread.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vibephoto.export.presets import BUILTIN_EXPORT_PRESETS, ExportPreset


class ExportDialog(QDialog):
    """Collects export settings for a batch of photos."""

    def __init__(self, count: int, default_dir: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export")
        self.setMinimumWidth(440)

        form = QFormLayout()
        self._preset = QComboBox()
        for preset in BUILTIN_EXPORT_PRESETS:
            self._preset.addItem(preset.name)
        form.addRow("Preset", self._preset)

        self._dest = QLineEdit(str(default_dir))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        dest_row = QHBoxLayout()
        dest_row.addWidget(self._dest, 1)
        dest_row.addWidget(browse)
        dest_widget = QWidget()
        dest_widget.setLayout(dest_row)
        form.addRow("Destination", dest_widget)

        self._bit_depth = QComboBox()
        self._bit_depth.addItem("8-bit", 8)
        self._bit_depth.addItem("16-bit (TIFF only)", 16)
        self._preset.currentIndexChanged.connect(self._sync_bit_depth)
        self._sync_bit_depth(self._preset.currentIndex())
        form.addRow("Bit depth", self._bit_depth)

        self._watermark = QLineEdit()
        self._watermark.setPlaceholderText("Optional watermark text")
        form.addRow("Watermark", self._watermark)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(f"Export {count}")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        heading = QLabel(f"Export {count} photo{'s' if count != 1 else ''}")
        heading.setStyleSheet("font-size:15px; font-weight:600; padding-bottom:6px;")
        layout.addWidget(heading)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Export Destination", self._dest.text())
        if chosen:
            self._dest.setText(chosen)

    def _sync_bit_depth(self, index: int) -> None:
        """16-bit is only meaningful for TIFF; disable the option otherwise."""
        preset = BUILTIN_EXPORT_PRESETS[index]
        is_tiff = preset.fmt.lower() in ("tif", "tiff")
        self._bit_depth.setEnabled(is_tiff)
        self._bit_depth.setCurrentIndex(1 if is_tiff and preset.bit_depth >= 16 else 0)

    def result_settings(self) -> tuple[ExportPreset, Path]:
        """The chosen preset (with watermark + bit depth applied) and destination."""
        preset = BUILTIN_EXPORT_PRESETS[self._preset.currentIndex()]
        watermark = self._watermark.text().strip()
        bit_depth = int(self._bit_depth.currentData()) if self._bit_depth.isEnabled() else 8
        if watermark or bit_depth != preset.bit_depth:
            preset = ExportPreset(
                preset.name, preset.fmt, preset.quality, preset.long_edge, watermark, bit_depth
            )
        return preset, Path(self._dest.text())
