"""Preset browser — a folder combo + a preset combo with live hover preview.

The top combo picks a preset folder (an imported pack, or "All"); the bottom combo
lists that folder's presets. Selecting a preset applies it; hovering one in the
dropdown renders the *current photo* with it and shows a small floating preview.
Parsed edit states and rendered previews are cached, so repeated hovers are cheap.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor, QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListView,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vibephoto.presets.loaders import PresetParseError, load_preset
from vibephoto.processing.edit_state import EditState

RenderFn = Callable[[EditState], QImage]
Group = tuple[str, list[tuple[str, Path]]]


class _PreviewPopup(QLabel):
    """A small frameless window that shows a preset preview near the cursor."""

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setStyleSheet("background:#0e0f11; border:1px solid #3a3d42; padding:3px;")

    def show_pixmap(self, pixmap: QPixmap) -> None:
        self.setPixmap(pixmap)
        self.adjustSize()
        pos = QCursor.pos()
        self.move(pos.x() - self.width() - 24, pos.y() - self.height() // 2)
        self.show()


class _HoverCombo(QComboBox):
    """A combo box that signals when its dropdown closes (to hide the preview)."""

    popup_closed = Signal()

    def hidePopup(self) -> None:
        super().hidePopup()
        self.popup_closed.emit()


class PresetBrowser(QWidget):
    """Folder + preset combo boxes with a hover preview popup."""

    preset_chosen = Signal(str, object)  # name, EditState
    add_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._render: RenderFn | None = None
        self._groups: dict[str, list[tuple[str, Path]]] = {}
        self._order: list[str] = []
        self._states: dict[str, EditState] = {}
        self._pixmaps: dict[str, QPixmap] = {}
        self._popup = _PreviewPopup()

        self._folder = QComboBox()
        self._folder.activated.connect(self._on_folder_changed)
        add = QPushButton("+")
        add.setFixedWidth(28)
        add.setToolTip("Add a preset folder to your library…")
        add.clicked.connect(self.add_requested.emit)

        self._preset = _HoverCombo()
        self._preset.setMaxVisibleItems(18)
        view = QListView()
        view.setMouseTracking(True)
        self._preset.setView(view)
        view.entered.connect(self._on_hover)
        self._preset.activated.connect(self._on_activated)
        self._preset.popup_closed.connect(self._popup.hide)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(4)
        top.addWidget(self._folder, 1)
        top.addWidget(add)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addLayout(top)
        layout.addWidget(self._preset)
        self.set_groups([])

    def set_render_callback(self, render: RenderFn | None) -> None:
        """Provide the function that renders an EditState to a preview image."""
        self._render = render
        self._pixmaps.clear()

    def set_groups(self, groups: list[Group]) -> None:
        """Populate the folder combo, then the preset combo for the first folder."""
        self._groups = dict(groups)
        self._order = [name for name, _ in groups]
        self._states.clear()
        self._pixmaps.clear()

        self._folder.blockSignals(True)
        self._folder.clear()
        if not groups:
            self._folder.addItem("No preset folders — click +", None)
        else:
            total = sum(len(items) for _, items in groups)
            self._folder.addItem(f"All folders ({total})", None)
            for name, items in groups:
                self._folder.addItem(f"{name}  ({len(items)})", name)
        self._folder.setCurrentIndex(0)
        self._folder.blockSignals(False)
        self._populate_presets()

    # -- internals ---------------------------------------------------------- #

    def _current_items(self) -> list[tuple[str, Path]]:
        data = self._folder.currentData()
        if not isinstance(data, str):  # "All folders"
            merged = [item for name in self._order for item in self._groups[name]]
            return sorted(merged, key=lambda item: item[0].lower())
        return self._groups.get(data, [])

    def _on_folder_changed(self, _index: int) -> None:
        self._populate_presets()

    def _populate_presets(self) -> None:
        items = self._current_items()
        self._preset.blockSignals(True)
        self._preset.clear()
        self._preset.addItem(f"Presets ({len(items)})…" if items else "— no presets —", None)
        for name, path in items:
            self._preset.addItem(name, str(path))
        self._preset.setCurrentIndex(0)
        self._preset.blockSignals(False)

    def _state_for(self, path_str: str) -> EditState | None:
        cached = self._states.get(path_str)
        if cached is not None:
            return cached
        try:
            _, state = load_preset(Path(path_str))
        except PresetParseError:
            return None
        self._states[path_str] = state
        return state

    def _on_activated(self, index: int) -> None:
        data = self._preset.itemData(index)
        self._popup.hide()
        if not isinstance(data, str):
            return
        state = self._state_for(data)
        if state is not None:
            self.preset_chosen.emit(self._preset.itemText(index), state)

    def _on_hover(self, index: object) -> None:
        if self._render is None or not hasattr(index, "data"):
            return
        data = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, str):
            self._popup.hide()
            return
        pixmap = self._preview_pixmap(data)
        if pixmap is None:
            self._popup.hide()
            return
        self._popup.show_pixmap(pixmap)

    def _preview_pixmap(self, path_str: str) -> QPixmap | None:
        cached = self._pixmaps.get(path_str)
        if cached is not None:
            return cached
        state = self._state_for(path_str)
        if state is None or self._render is None:
            return None
        pixmap = QPixmap.fromImage(self._render(state))
        self._pixmaps[path_str] = pixmap
        return pixmap

    def leaveEvent(self, event: object) -> None:
        self._popup.hide()
