"""The main application window — the workspace shell.

Implements the professional layout: a module switcher in the top toolbar, a
central area that swaps between modules, dockable side/bottom panels, a menu bar
with industry-standard shortcuts, and a status bar. Workspace geometry and
dock layout persist between sessions via :class:`QSettings`.

The window is constructed from an :class:`~vibephoto.app.application.Application`
and reads configuration and the event bus from it. It owns no domain logic;
panels and modules bind to services resolved from the container as later phases
add them.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QThreadPool
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QStackedWidget,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from vibephoto import APP_AUTHOR, APP_NAME, __version__
from vibephoto.app.application import Application
from vibephoto.cache.thumbnails import ThumbnailCache
from vibephoto.catalog.indexer import IndexerService, IndexResult
from vibephoto.catalog.models import Photo
from vibephoto.catalog.service import CatalogService
from vibephoto.export.service import ExportItem, ExportResult, ExportService
from vibephoto.processing.clipboard import SettingsClipboard
from vibephoto.processing.engine import DevelopEngine
from vibephoto.processing.layers import LayerStack
from vibephoto.processing.store import DevelopStore
from vibephoto.ui.batch_worker import BatchAutoEditRunnable, BatchItem
from vibephoto.ui.develop_module import DevelopModule
from vibephoto.ui.export_dialog import ExportDialog
from vibephoto.ui.export_worker import ExportRunnable
from vibephoto.ui.filmstrip import Filmstrip
from vibephoto.ui.import_worker import ImportRunnable
from vibephoto.ui.module_views import LibraryModule, ModuleId, ModuleView
from vibephoto.ui.photo_grid import PhotoGridModel
from vibephoto.ui.qt_bridge import QtEventBridge
from vibephoto.ui.spinner import BusySpinner

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Top-level workspace window."""

    def __init__(self, app: Application) -> None:
        super().__init__()
        self._app = app
        self._modules: dict[ModuleId, ModuleView] = {}
        self._module_actions: dict[ModuleId, QAction] = {}
        self._current_module: ModuleId | None = None

        self.setObjectName("MainWindow")
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(1440, 900)
        self.setDockOptions(
            QMainWindow.DockOption.AnimatedDocks
            | QMainWindow.DockOption.AllowNestedDocks
            | QMainWindow.DockOption.AllowTabbedDocks
        )

        self._threadpool = QThreadPool.globalInstance()
        self._bridge = QtEventBridge(app.events)
        self._bridge.index_progress.connect(self._on_index_progress)

        self._build_central()
        self._build_docks()
        self._build_toolbar()
        self._build_menus()
        self._build_status_bar()

        self._switch_module(ModuleId.LIBRARY)
        self._restore_workspace()
        self._reload_filmstrip()
        self._reload_navigator()

    # -- Construction ------------------------------------------------------- #

    def _build_central(self) -> None:
        self._stack = QStackedWidget(self)
        self._library = LibraryModule(self._app, self)
        self._develop = DevelopModule(self._app, self)
        self._library.photo_activated.connect(self._open_in_develop)
        self._library.photos_changed.connect(self._reload_filmstrip)
        self._library.settings_pasted.connect(self._on_library_settings_pasted)
        self._library.auto_requested.connect(self._batch_auto)
        self._develop.paste_to_selected_requested.connect(self._paste_to_selected)
        self._develop.render_busy_changed.connect(self._set_busy)
        self._develop.photo_nav_requested.connect(self._on_develop_nav)
        for module in (self._library, self._develop):
            self._modules[module.module_id] = module
            self._stack.addWidget(module)
        self.setCentralWidget(self._stack)

    def _make_dock(
        self, title: str, obj_name: str, body: QWidget, area: Qt.DockWidgetArea
    ) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(obj_name)  # required for QSettings state persistence
        dock.setWidget(body)
        dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.addDockWidget(area, dock)
        return dock

    def _build_docks(self) -> None:
        # Left: catalog navigator (folders), bound to the live catalog.
        self._nav = QTreeWidget()
        self._nav.setHeaderHidden(True)
        self._nav.itemClicked.connect(self._on_nav_clicked)
        self._dock_catalog = self._make_dock(
            "Catalog", "dock.catalog", self._nav, Qt.DockWidgetArea.LeftDockWidgetArea
        )

        # The Develop adjustments live in the Develop module's own right-hand panel
        # (canvas + panel), so no separate Adjustments dock is needed here.

        # Bottom: a live filmstrip bound to the catalog.
        self._filmstrip_model = PhotoGridModel(self._app.resolve(ThumbnailCache))
        self._filmstrip = Filmstrip(self._filmstrip_model)
        self._filmstrip.photo_clicked.connect(self._on_filmstrip_clicked)
        self._dock_filmstrip = self._make_dock(
            "Filmstrip", "dock.filmstrip", self._filmstrip, Qt.DockWidgetArea.BottomDockWidgetArea
        )

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Modules", self)
        toolbar.setObjectName("toolbar.modules")
        toolbar.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)

        group = QActionGroup(self)
        group.setExclusive(True)
        for module_id, label, shortcut in (
            (ModuleId.LIBRARY, "Library", "G"),
            (ModuleId.DEVELOP, "Develop", "D"),
        ):
            action = QAction(label, self)
            action.setCheckable(True)
            action.setShortcut(QKeySequence(shortcut))
            action.setToolTip(f"{label} module ({shortcut})")
            action.triggered.connect(lambda _checked, m=module_id: self._switch_module(m))
            group.addAction(action)
            toolbar.addAction(action)
            self._module_actions[module_id] = action

    def _build_menus(self) -> None:
        menubar = self.menuBar()

        file_menu = menubar.addMenu("&File")
        self._add_action(file_menu, "Import Folder…", "Ctrl+Shift+I", self._import_folder)
        self._add_action(file_menu, "Open Catalog…", "Ctrl+O", self._not_yet("Open Catalog"))
        file_menu.addSeparator()
        self._add_action(file_menu, "Export…", "Ctrl+Shift+E", self._export_selected)
        file_menu.addSeparator()
        quit_action = self._add_action(file_menu, "Quit", "Ctrl+Q", self.close)
        quit_action.setMenuRole(QAction.MenuRole.QuitRole)

        view_menu = menubar.addMenu("&View")
        self._add_action(
            view_menu, "Library (Grid)", "G", lambda: self._switch_module(ModuleId.LIBRARY)
        )
        self._add_action(
            view_menu, "Develop", "D", lambda: self._switch_module(ModuleId.DEVELOP)
        )
        view_menu.addSeparator()
        self._add_action(view_menu, "Toggle Fullscreen", "F", self._toggle_fullscreen)
        view_menu.addSeparator()
        # Dock visibility toggles come free from Qt.
        for dock in (self._dock_catalog, self._dock_filmstrip):
            view_menu.addAction(dock.toggleViewAction())

        window_menu = menubar.addMenu("&Window")
        self._add_action(window_menu, "Reset Workspace", None, self._reset_workspace)

        help_menu = menubar.addMenu("&Help")
        about = self._add_action(help_menu, f"About {APP_NAME}", None, self._show_about)
        about.setMenuRole(QAction.MenuRole.AboutRole)

    def _build_status_bar(self) -> None:
        self._status_module = QLabel("Library")
        self._batch_label = "Auto"  # current batch job's display name
        version = QLabel(f"{APP_NAME} {__version__}")
        # Bottom-corner busy indicator: a progress bar (batch jobs) + a spinner
        # (any background work, e.g. a develop render in flight).
        self._progress = QProgressBar()
        self._progress.setFixedWidth(140)
        self._progress.setTextVisible(False)
        self._progress.setVisible(False)
        self._spinner = BusySpinner()
        self.statusBar().addWidget(self._status_module, 1)
        self.statusBar().addPermanentWidget(self._progress)
        self.statusBar().addPermanentWidget(self._spinner)
        self.statusBar().addPermanentWidget(version)

    def _set_busy(self, busy: bool) -> None:
        """Show/hide the corner spinner for background activity."""
        self._spinner.set_active(busy)

    # -- Behaviour ---------------------------------------------------------- #

    def _switch_module(self, module_id: ModuleId) -> None:
        # Leaving Develop: persist any in-progress edit before the surface changes.
        if self._current_module is ModuleId.DEVELOP and module_id is not ModuleId.DEVELOP:
            self._develop.commit()

        module = self._modules[module_id]
        self._stack.setCurrentWidget(module)
        module.on_activated()
        action = self._module_actions.get(module_id)
        if action is not None and not action.isChecked():
            action.setChecked(True)
        self._status_module.setText(module_id.value.capitalize())

        # Entering Develop from the toolbar/shortcut: edit the selected photo.
        if module_id is ModuleId.DEVELOP and self._current_module is not ModuleId.DEVELOP:
            photo = self._library.selected_photo()
            if photo is not None:
                self._develop.load_photo(photo)

        self._current_module = module_id
        logger.debug("Switched to %s module", module_id.value)

    def _open_in_develop(self, photo: Photo) -> None:
        """Open a specific photo in Develop (from a Library double-click)."""
        self._develop.load_photo(photo)
        self._filmstrip.select_photo(photo)
        self._switch_module(ModuleId.DEVELOP)

    def _on_filmstrip_clicked(self, photo: Photo) -> None:
        """A filmstrip frame was clicked: edit it if in Develop, else open it there."""
        if self._current_module is ModuleId.DEVELOP:
            self._develop.load_photo(photo)
        else:
            self._open_in_develop(photo)

    def _on_develop_nav(self, direction: int) -> None:
        """Left/Right in Develop: step to the previous/next photo in the filmstrip set."""
        photos = self._library.current_photos()
        if not photos:
            return
        current = self._develop.requested_photo
        index = 0
        if current is not None and current.id is not None:
            ids = [photo.id for photo in photos]
            if current.id in ids:
                # Clamp at the ends (no wrap-around) — matches pro-editor behaviour.
                index = max(0, min(len(photos) - 1, ids.index(current.id) + direction))
                if photos[index].id == current.id:
                    return  # already at the first/last photo
        target = photos[index]
        self._develop.load_photo(target)
        self._filmstrip.select_photo(target)

    def _reload_filmstrip(self) -> None:
        # Mirror the Library's current (folder + rating filtered) set, so the
        # Develop filmstrip only shows the photos you're working with.
        self._filmstrip_model.set_photos(self._library.current_photos())

    def _reload_navigator(self) -> None:
        """Rebuild the left navigator tree from the catalog's folders."""
        self._nav.clear()
        all_item = QTreeWidgetItem(["All Photographs"])
        all_item.setData(0, Qt.ItemDataRole.UserRole, None)
        self._nav.addTopLevelItem(all_item)
        catalog = self._app.resolve(CatalogService)
        if not catalog.is_open:
            return
        folders = catalog.folders.list_all()
        if not folders:
            return
        root = QTreeWidgetItem(["Folders"])
        self._nav.addTopLevelItem(root)
        for folder in folders:
            child = QTreeWidgetItem([folder.name or folder.path])
            child.setData(0, Qt.ItemDataRole.UserRole, folder.id)
            root.addChild(child)
        root.setExpanded(True)

    def _on_nav_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        folder_id = data if isinstance(data, int) else None
        self._library.show_folder(folder_id)
        self._switch_module(ModuleId.LIBRARY)

    # -- Import ------------------------------------------------------------- #

    def _import_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Import Folder")
        if not folder:
            return
        runnable = ImportRunnable(
            Path(folder),
            self._app.resolve(IndexerService),
            self._app.resolve(CatalogService),
            self._app.resolve(ThumbnailCache),
        )
        runnable.signals.finished.connect(self._on_import_finished)
        runnable.signals.failed.connect(self._on_import_failed)
        self.statusBar().showMessage(f"Importing {folder}…")
        self._threadpool.start(runnable)

    def _on_index_progress(self, event: object) -> None:
        processed = getattr(event, "processed", 0)
        total = getattr(event, "total", 0)
        self.statusBar().showMessage(f"Indexing… {processed}/{total}")

    def _on_import_finished(self, result: IndexResult) -> None:
        self._switch_module(ModuleId.LIBRARY)
        self._library.reload()
        self._reload_filmstrip()
        self._reload_navigator()
        self.statusBar().showMessage(
            f"Imported {result.imported}, skipped {result.skipped}, "
            f"failed {result.failed}",
            8000,
        )

    def _on_import_failed(self, message: str) -> None:
        self.statusBar().clearMessage()
        QMessageBox.warning(self, "Import failed", message)

    # -- Export ------------------------------------------------------------- #

    def _export_targets(self) -> list[Photo]:
        """Photos to export: the Library selection, else the photo open in Develop."""
        photos = self._library.selected_photos()
        if not photos and self._develop.current_photo is not None:
            photos = [self._develop.current_photo]
        return photos

    def _export_selected(self) -> None:
        photos = self._export_targets()
        catalog = self._app.resolve(CatalogService)
        items: list[ExportItem] = []
        for photo in photos:
            path = catalog.resolve_path(photo)
            if path is not None and path.exists():
                items.append(ExportItem(path, photo.is_raw, photo.id))
        if not items:
            QMessageBox.information(
                self, "Export", "Select one or more photos in the Library first."
            )
            return

        dialog = ExportDialog(len(items), self._app.paths.exports_dir, self)
        if dialog.exec() != ExportDialog.DialogCode.Accepted:
            return
        preset, dest = dialog.result_settings()
        dest.mkdir(parents=True, exist_ok=True)

        runnable = ExportRunnable(self._app.resolve(ExportService), items, preset, dest)
        runnable.signals.progress.connect(self._on_export_progress)
        runnable.signals.finished.connect(self._on_export_finished)
        runnable.signals.failed.connect(self._on_export_failed)
        self.statusBar().showMessage(f"Exporting {len(items)} photo(s)…")
        self._threadpool.start(runnable)

    def _on_export_progress(self, done: int, total: int) -> None:
        self.statusBar().showMessage(f"Exporting… {done}/{total}")

    def _on_export_finished(self, result: ExportResult) -> None:
        self.statusBar().showMessage(
            f"Exported {result.exported}, failed {result.failed}", 8000
        )
        if result.outputs:
            QMessageBox.information(
                self,
                "Export complete",
                f"Exported {result.exported} photo(s) to:\n{result.outputs[0].parent}",
            )

    def _on_export_failed(self, message: str) -> None:
        self.statusBar().clearMessage()
        QMessageBox.warning(self, "Export failed", message)

    # -- Paste settings to a selection -------------------------------------- #

    def _paste_to_selected(self) -> None:
        """Paste the copied settings onto every selected photo (Shift+Paste)."""
        pasted = self._app.resolve(SettingsClipboard).paste()
        if pasted is None:
            return
        photos = self._library.selected_photos()
        if not photos and self._develop.current_photo is not None:
            photos = [self._develop.current_photo]
        store = self._app.resolve(DevelopStore)
        count = 0
        affected_ids = set()
        for photo in photos:
            if photo.id is not None:
                store.save(photo.id, LayerStack.single(pasted))
                affected_ids.add(photo.id)
                count += 1
        current = self._develop.current_photo
        if current is not None and current.id in affected_ids:
            self._develop.refresh_from_store()
        self.statusBar().showMessage(f"Pasted settings to {count} photo(s)", 6000)

    # -- Batch Auto Edit ---------------------------------------------------- #

    def _batch_auto(self, photos: list[Photo], kind: str) -> None:
        """Auto-edit / auto-HDR a list of photos off-thread, with progress + spinner."""
        label = "Auto HDR" if kind == "hdr" else "Auto Edit"
        catalog = self._app.resolve(CatalogService)
        items: list[BatchItem] = []
        for photo in photos:
            if photo.id is None:
                continue
            path = catalog.resolve_path(photo)
            if path is not None and path.exists():
                items.append(BatchItem(path, photo.id, photo.is_raw))
        if not items:
            QMessageBox.information(self, label, "No editable photos selected.")
            return

        self._batch_label = label
        runnable = BatchAutoEditRunnable(
            items, self._app.resolve(DevelopEngine).loader, self._app.resolve(DevelopStore), kind
        )
        runnable.signals.progress.connect(self._on_batch_progress)
        runnable.signals.finished.connect(self._on_batch_finished)
        runnable.signals.failed.connect(self._on_batch_failed)
        self._progress.setRange(0, len(items))
        self._progress.setValue(0)
        self._progress.setVisible(True)
        self._spinner.set_active(True)
        self.statusBar().showMessage(f"{label}: {len(items)} photo(s)…")
        self._threadpool.start(runnable)

    def _on_batch_progress(self, done: int, total: int) -> None:
        self._progress.setValue(done)
        self.statusBar().showMessage(f"{self._batch_label}… {done}/{total}")

    def _on_batch_finished(self, succeeded: int, total: int) -> None:
        self._progress.setVisible(False)
        self._spinner.set_active(False)
        self.statusBar().showMessage(f"{self._batch_label}: {succeeded}/{total} photo(s)", 6000)
        if self._develop.current_photo is not None:
            self._develop.refresh_from_store()  # reflect the new edit if it's open

    def _on_batch_failed(self, message: str) -> None:
        self._progress.setVisible(False)
        self._spinner.set_active(False)
        QMessageBox.warning(self, getattr(self, "_batch_label", "Auto"), f"Batch failed: {message}")

    def _on_library_settings_pasted(self) -> None:
        """A Library Paste touched the catalog; refresh Develop if it's affected."""
        if self._develop.current_photo is not None:
            self._develop.refresh_from_store()

    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            f"About {APP_NAME}",
            f"<h3>{APP_NAME} {__version__}</h3>"
            "<p>A professional, high-performance RAW photo editor and catalog "
            "manager.</p>"
            "<p>Phases 1 &amp; 2 — foundation and catalog.</p>",
        )

    def _not_yet(self, feature: str) -> Callable[[], None]:
        def handler() -> None:
            QMessageBox.information(
                self, feature, f"{feature} is part of a later development phase."
            )

        return handler

    # -- Workspace persistence --------------------------------------------- #

    def _qsettings(self) -> QSettings:
        return QSettings(APP_AUTHOR, APP_NAME)

    def _restore_workspace(self) -> None:
        if not self._app.settings.ui.restore_workspace:
            return
        s = self._qsettings()
        geometry = s.value("workspace/geometry")
        state = s.value("workspace/state")
        if geometry is not None:
            self.restoreGeometry(geometry)
        if state is not None:
            self.restoreState(state)

    def _save_workspace(self) -> None:
        s = self._qsettings()
        s.setValue("workspace/geometry", self.saveGeometry())
        s.setValue("workspace/state", self.saveState())

    def _reset_workspace(self) -> None:
        s = self._qsettings()
        s.remove("workspace/geometry")
        s.remove("workspace/state")
        QMessageBox.information(
            self, "Reset Workspace", "Workspace will reset to defaults on next launch."
        )

    # -- Qt overrides ------------------------------------------------------- #

    def closeEvent(self, event: QCloseEvent) -> None:
        self._develop.commit()  # flush any pending edit to disk
        if self._app.settings.ui.restore_workspace:
            self._save_workspace()
        super().closeEvent(event)

    # -- Helpers ------------------------------------------------------------ #

    def _add_action(
        self, menu: QMenu, text: str, shortcut: str | None, handler: Callable[[], object]
    ) -> QAction:
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(lambda _checked=False: handler())
        menu.addAction(action)
        return action
