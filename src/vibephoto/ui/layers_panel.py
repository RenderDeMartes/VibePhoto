"""Layers panel — list, add, delete, enable, and select edit layers.

A compact list of the photo's edit layers (bottom layer first, "Base" on top of
the list). Clicking a layer makes it the active one the sliders edit; the
checkbox toggles whether a layer is applied; the buttons add/remove layers. The
panel is purely a view — the :class:`DevelopModule` owns the stack and pushes it
back in via :meth:`set_stack`.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vibephoto.processing.layers import LayerStack


class LayersPanel(QWidget):
    """Lists the edit layers with add/delete and enable controls."""

    layer_selected = Signal(int)
    layer_added = Signal()
    layer_removed = Signal()
    layer_toggled = Signal(int, bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._syncing = False
        self._count = 1  # number of layers (for row<->stack-index mapping)

        header = QLabel("LAYERS")
        header.setStyleSheet(
            "color:#8a8d93; font-size:11px; font-weight:600; letter-spacing:1px; padding:4px 0 2px;"
        )
        self._list = QListWidget()
        self._list.setMaximumHeight(130)
        self._list.currentRowChanged.connect(self._on_row_changed)
        self._list.itemChanged.connect(self._on_item_changed)

        add = QPushButton("+ Layer")
        add.setToolTip("Add a new edit layer on top")
        add.clicked.connect(self.layer_added.emit)
        remove = QPushButton("Delete")
        remove.setToolTip("Delete the selected layer")
        remove.clicked.connect(self.layer_removed.emit)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.addWidget(add)
        buttons.addWidget(remove)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(3)
        layout.addWidget(header)
        layout.addWidget(self._list)
        layout.addLayout(buttons)

    def set_stack(self, stack: LayerStack) -> None:
        """Rebuild the list — top layer first (newest on top), like professional layer editors."""
        self._syncing = True
        self._count = len(stack.layers)
        self._list.clear()
        for layer in reversed(stack.layers):  # display top-to-bottom
            item = QListWidgetItem(layer.name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if layer.enabled else Qt.CheckState.Unchecked
            )
            self._list.addItem(item)
        self._list.setCurrentRow(self._stack_index(stack.active))
        self._syncing = False

    def _stack_index(self, row: int) -> int:
        """Map a list row (top-first) to a stack index (bottom-first)."""
        return self._count - 1 - row

    def _on_row_changed(self, row: int) -> None:
        if not self._syncing and row >= 0:
            self.layer_selected.emit(self._stack_index(row))

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        if self._syncing:
            return
        index = self._stack_index(self._list.row(item))
        self.layer_toggled.emit(index, item.checkState() == Qt.CheckState.Checked)
