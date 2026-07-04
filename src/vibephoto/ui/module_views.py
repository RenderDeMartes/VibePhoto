"""Module views — the swappable central surfaces of the workspace.

Vibe Photo, like other professional editors, is organised into *modules* (Library, Develop, …)
shown one at a time in the central area. This file defines the module contract,
the live **Library** grid (bound to the catalog as of Phase 2), and the Develop
shell (its editing surface arrives in Phase 4). The main window hosts and switches
modules uniformly through :class:`ModuleView`.
"""

from __future__ import annotations

from enum import Enum

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from vibephoto.app.application import Application
from vibephoto.cache.thumbnails import ThumbnailCache
from vibephoto.catalog.models import Photo
from vibephoto.catalog.service import CatalogService
from vibephoto.presets.library import PresetLibrary
from vibephoto.presets.loaders import PresetParseError, load_preset
from vibephoto.processing.batch import apply_preset_to_photo
from vibephoto.processing.clipboard import SettingsClipboard
from vibephoto.processing.layers import LayerStack
from vibephoto.processing.store import DevelopStore
from vibephoto.ui.apply_preset_dialog import ApplyPresetDialog
from vibephoto.ui.photo_grid import LibraryGrid, PhotoGridModel


class ModuleId(Enum):
    """Identifiers for the workspace modules."""

    LIBRARY = "library"
    DEVELOP = "develop"


class ModuleView(QWidget):
    """Base class for a central module surface."""

    module_id: ModuleId

    def on_activated(self) -> None:
        """Called when the module becomes the active central surface."""


class LibraryModule(ModuleView):
    """Grid/Loupe library surface backed by the catalog."""

    module_id = ModuleId.LIBRARY

    #: Emitted when a photo is activated (double-clicked) — the shell opens Develop.
    photo_activated = Signal(object)  # Photo
    #: Emitted whenever the visible photo set changes (so the filmstrip can mirror it).
    photos_changed = Signal()
    #: Emitted after settings are pasted onto photos (so Develop can refresh).
    settings_pasted = Signal()
    #: Emitted to auto-process a batch of photos off-thread: (photos, kind) where
    #: kind is "edit" (auto-tone) or "hdr" (single-image HDR look).
    auto_requested = Signal(object, str)
    #: Emitted when the minimum-rating filter changes (so mirrors, e.g. the
    #: filmstrip's filter bar, can stay in sync).
    min_rating_changed = Signal(int)

    def __init__(self, app: Application, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._app = app
        self._catalog = app.resolve(CatalogService)
        self._store = app.resolve(DevelopStore)
        self._clipboard = app.resolve(SettingsClipboard)
        self._presets = app.resolve(PresetLibrary)
        self._folder_filter: int | None = None  # None = all photographs
        self._min_rating = 0  # 0 = show all; N = only photos rated >= N
        thumbnails = app.resolve(ThumbnailCache)

        self._model = PhotoGridModel(thumbnails, self)
        self._grid = LibraryGrid(self._model, self)
        self._grid.doubleClicked.connect(self._on_double_click)
        self._grid.rating_key.connect(self._apply_rating)
        self._grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._grid.customContextMenuRequested.connect(self._on_context_menu)

        self._count_label = QLabel("No photos yet")
        self._count_label.setStyleSheet("color: #9a9da3; padding: 6px 10px;")

        self._empty = _empty_state()
        self._stack = QStackedWidget(self)
        self._stack.addWidget(self._empty)  # index 0
        self._stack.addWidget(self._grid)  # index 1

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_filter_bar())
        layout.addWidget(self._stack, 1)

    def _build_filter_bar(self) -> QWidget:
        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 8, 0)
        bar.addWidget(self._count_label, 1)
        hint = QLabel("Rating ≥")
        hint.setStyleSheet("color:#9a9da3; padding-right:4px;")
        bar.addWidget(hint)
        self._rating_filter = QButtonGroup(self)
        self._rating_filter.setExclusive(True)
        for label, value in (("All", 0), ("1★", 1), ("2★", 2), ("3★", 3), ("4★", 4), ("5★", 5)):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setChecked(value == 0)
            button.setFixedHeight(24)
            button.setStyleSheet(
                "QPushButton:checked{background:#3d8bfd; color:#fff; border-color:#3d8bfd;}"
            )
            button.clicked.connect(lambda _checked=False, v=value: self.set_min_rating(v))
            self._rating_filter.addButton(button, value)
            bar.addWidget(button)
        widget = QWidget()
        widget.setLayout(bar)
        return widget

    def on_activated(self) -> None:
        self.reload()

    def show_folder(self, folder_id: int | None) -> None:
        """Filter the grid to one catalog folder (``None`` = all photographs)."""
        self._folder_filter = folder_id
        self.reload()

    def set_min_rating(self, minimum: int) -> None:
        """Show only photos rated at least ``minimum`` stars (0 = all)."""
        self._min_rating = minimum
        button = self._rating_filter.button(minimum)
        if button is not None and not button.isChecked():
            button.setChecked(True)  # keep the Library bar in sync with mirrors
        self.reload()
        self.min_rating_changed.emit(minimum)

    def current_photos(self) -> list[Photo]:
        """The photos currently visible in the grid (after folder + rating filters)."""
        return list(self._model.photos())

    def reload(self) -> None:
        """Refresh the grid from the catalog, honouring the folder + rating filters."""
        if not self._catalog.is_open:
            photos: list[Photo] = []
        elif self._folder_filter is None:
            photos = self._catalog.photos.list_all()
        else:
            photos = self._catalog.photos.list_by_folder(self._folder_filter)
        if self._min_rating > 0:
            photos = [photo for photo in photos if photo.rating >= self._min_rating]
        self._model.set_photos(photos)
        if photos:
            label = f"{len(photos):,} photo{'s' if len(photos) != 1 else ''}"
            if self._min_rating > 0:
                label += f"  ·  ★{self._min_rating}+"
            self._count_label.setText(label)
            self._stack.setCurrentWidget(self._grid)
        else:
            self._count_label.setText(
                "No photos match this filter" if self._min_rating > 0 else "No photos yet"
            )
            self._stack.setCurrentWidget(self._empty)
        self.photos_changed.emit()

    def _apply_rating(self, rating: int) -> None:
        """Assign ``rating`` stars to the selected photos (0-5 keys)."""
        rows = sorted({idx.row() for idx in self._grid.selectionModel().selectedIndexes()})
        if not rows and self._grid.currentIndex().isValid():
            rows = [self._grid.currentIndex().row()]
        changed = 0
        for row in rows:
            photo = self._model.photo_at(row)
            if photo is not None and photo.id is not None:
                self._catalog.photos.set_rating(photo.id, rating)
                self._model.update_rating(row, rating)
                changed += 1
        if changed:
            star = f"{rating}★" if rating else "no stars"
            self._count_label.setText(f"Set {star} on {changed} photo{'s' if changed != 1 else ''}")

    def _on_context_menu(self, pos: QPoint) -> None:
        """Right-click: copy settings from a photo, or paste onto the selection."""
        index = self._grid.indexAt(pos)
        photo = self._model.photo_at(index.row()) if index.isValid() else None
        targets = self.selected_photos() or ([photo] if photo is not None else [])

        all_photos = self.current_photos()
        menu = QMenu(self)
        auto_action = menu.addAction(f"Auto Edit → {len(targets)} photo(s)")
        auto_action.setEnabled(bool(targets))
        auto_all_action = menu.addAction(f"Auto Edit All ({len(all_photos)})")
        auto_all_action.setEnabled(bool(all_photos))
        menu.addSeparator()
        hdr_action = menu.addAction(f"Auto HDR → {len(targets)} photo(s)")
        hdr_action.setEnabled(bool(targets))
        hdr_all_action = menu.addAction(f"Auto HDR All ({len(all_photos)})")
        hdr_all_action.setEnabled(bool(all_photos))
        menu.addSeparator()
        apply_preset_action = menu.addAction(f"Apply Preset… → {len(targets)} photo(s)")
        apply_preset_action.setEnabled(bool(targets))
        menu.addSeparator()
        reset_action = menu.addAction(f"Reset to Original → {len(targets)} photo(s)")
        reset_action.setEnabled(bool(targets))
        reset_all_action = menu.addAction(f"Reset All to Original ({len(all_photos)})")
        reset_all_action.setEnabled(bool(all_photos))
        menu.addSeparator()
        copy_action = menu.addAction("Copy Settings")
        copy_action.setEnabled(photo is not None and photo.id is not None)
        paste_action = menu.addAction(f"Paste Settings → {len(targets)} photo(s)")
        paste_action.setEnabled(self._clipboard.has_settings and bool(targets))

        chosen = menu.exec(self._grid.mapToGlobal(pos))
        if chosen is apply_preset_action:
            self._apply_preset_to(targets)
        elif chosen is reset_action:
            self._reset_edits(targets)
        elif chosen is reset_all_action:
            self._reset_edits(all_photos, confirm=True)
        elif chosen is auto_action:
            self.auto_requested.emit(targets, "edit")
        elif chosen is auto_all_action:
            self.auto_requested.emit(all_photos, "edit")
        elif chosen is hdr_action:
            self.auto_requested.emit(targets, "hdr")
        elif chosen is hdr_all_action:
            self.auto_requested.emit(all_photos, "hdr")
        elif chosen is copy_action and photo is not None and photo.id is not None:
            self._clipboard.copy(self._store.load(photo.id).active_state)
            self._count_label.setText(f"Copied settings from {photo.filename}")
        elif chosen is paste_action:
            pasted = self._clipboard.paste()
            if pasted is None:
                return
            count = 0
            for target in targets:
                if target.id is not None:
                    self._store.save(target.id, LayerStack.single(pasted))
                    count += 1
            self._count_label.setText(f"Pasted settings to {count} photo(s)")
            self.settings_pasted.emit()

    def _reset_edits(self, targets: list[Photo], *, confirm: bool = False) -> None:
        """Reset every target photo's develop settings back to the original.

        Non-destructive editing means "reset" is just storing an identity stack
        (which deletes the edit file) — the image files are never touched.
        """
        if not targets:
            return
        if confirm:
            answer = QMessageBox.question(
                self,
                "Reset All to Original",
                f"Reset ALL edits on {len(targets)} photo(s) back to the original?\n\n"
                "Crops, adjustments, layers, and masks are removed. "
                "The image files themselves are not modified.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        count = 0
        for target in targets:
            if target.id is not None:
                self._store.save(target.id, LayerStack.single())
                count += 1
        self._count_label.setText(f"Reset {count} photo(s) to original")
        self.settings_pasted.emit()  # Develop reloads if it has one of these open

    def _apply_preset_to(self, targets: list[Photo]) -> None:
        """Apply a chosen preset to every target, on a new or the same layer."""
        if not targets:
            return
        groups = self._presets.list_groups()
        if not any(presets for _g, presets in groups):
            self._count_label.setText("No presets in your library — import some first.")
            return
        dialog = ApplyPresetDialog(groups, len(targets), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        path = dialog.chosen_preset()
        if path is None:
            return
        try:
            name, state = load_preset(path)
        except PresetParseError:
            self._count_label.setText(f"Could not read preset: {path.name}")
            return

        new_layer = dialog.mode() == "new"
        count = 0
        for target in targets:
            if target.id is None:
                continue
            apply_preset_to_photo(self._store, target.id, name, state, new_layer=new_layer)
            count += 1
        where = "a new layer" if new_layer else "the base layer"
        self._count_label.setText(f"Applied '{name}' to {count} photo(s) on {where}")
        self.settings_pasted.emit()

    def selected_photo(self) -> Photo | None:
        """The currently-selected (or first-selected) photo, if any."""
        index = self._grid.currentIndex()
        if not index.isValid():
            selected = self._grid.selectionModel().selectedIndexes()
            if not selected:
                return None
            index = selected[0]
        return self._model.photo_at(index.row())

    def selected_photos(self) -> list[Photo]:
        """All currently-selected photos (for batch actions like export)."""
        rows = sorted({idx.row() for idx in self._grid.selectionModel().selectedIndexes()})
        photos = [self._model.photo_at(row) for row in rows]
        return [photo for photo in photos if photo is not None]

    def _on_double_click(self, index: QModelIndex | QPersistentModelIndex) -> None:
        photo = self._model.photo_at(index.row())
        if photo is not None:
            self.photo_activated.emit(photo)


def _empty_state() -> QWidget:
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
    heading = QLabel("Your library is empty")
    heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
    heading.setStyleSheet("font-size: 20px; font-weight: 600; color: #e6e7e9;")
    caption = QLabel("Use File → Import Folder… (Ctrl+Shift+I) to add photos.")
    caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
    caption.setStyleSheet("font-size: 13px; color: #9a9da3;")
    layout.addWidget(heading)
    layout.addSpacing(8)
    layout.addWidget(caption)
    return widget
