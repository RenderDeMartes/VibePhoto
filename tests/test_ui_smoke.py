"""GUI smoke tests for the main window.

Marked ``gui`` and skipped automatically when PySide6 is not installed, so the
headless core suite (``pytest -m 'not gui'``) never requires Qt. Runs with the
offscreen Qt platform so it works in CI without a display server.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from vibephoto.app.bootstrap import build_application
from vibephoto.core.config import AppSettings
from vibephoto.core.paths import AppPaths
from vibephoto.ui.main_window import MainWindow
from vibephoto.ui.module_views import ModuleId
from vibephoto.ui.theme import apply_theme

pytestmark = pytest.mark.gui


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def app(tmp_path):
    paths = AppPaths.under(tmp_path).ensure()
    # restore_workspace off so the test doesn't read host QSettings.
    settings = AppSettings()
    settings.ui.restore_workspace = False
    return build_application(paths=paths, settings=settings, configure_logs=False)


def test_apply_theme_runs(qapp: QApplication, app) -> None:
    apply_theme(qapp, app.settings.general)
    assert qapp.styleSheet()  # stylesheet loaded from resources


def test_main_window_constructs_and_has_modules(qapp: QApplication, app) -> None:
    window = MainWindow(app)
    assert window.windowTitle().startswith("Vibe Photo")
    assert set(window._modules.keys()) == {ModuleId.LIBRARY, ModuleId.DEVELOP}
    window.close()


def test_module_switching_updates_central_and_status(qapp: QApplication, app) -> None:
    window = MainWindow(app)
    window._switch_module(ModuleId.DEVELOP)
    assert window._stack.currentWidget() is window._modules[ModuleId.DEVELOP]
    assert window._status_module.text() == "Develop"
    window._switch_module(ModuleId.LIBRARY)
    assert window._status_module.text() == "Library"
    window.close()


def test_docks_exist_with_object_names(qapp: QApplication, app) -> None:
    window = MainWindow(app)
    names = {d.objectName() for d in window.findChildren(type(window._dock_catalog))}
    assert {"dock.catalog", "dock.filmstrip"} <= names
    window.close()


def test_photo_grid_model_basic(qapp: QApplication, app) -> None:
    from datetime import datetime

    from PySide6.QtCore import Qt

    from vibephoto.cache.thumbnails import ThumbnailCache
    from vibephoto.catalog.models import Photo
    from vibephoto.ui.photo_grid import PhotoGridModel

    model = PhotoGridModel(app.resolve(ThumbnailCache))
    assert model.rowCount() == 0
    model.set_photos(
        [Photo(folder_id=1, filename="a.jpg", file_ext="jpg", import_time=datetime.now(), id=1)]
    )
    assert model.rowCount() == 1
    index = model.index(0, 0)
    assert model.data(index, Qt.ItemDataRole.DisplayRole) == "a.jpg"
    # DecorationRole returns a (placeholder) pixmap, never None.
    assert model.data(index, Qt.ItemDataRole.DecorationRole) is not None


def test_library_module_binds_to_catalog(qapp: QApplication, tmp_path, make_jpeg) -> None:
    from vibephoto.catalog.indexer import IndexerService
    from vibephoto.ui.module_views import LibraryModule

    paths = AppPaths.under(tmp_path / "bound").ensure()
    settings = AppSettings()
    settings.catalog.backup_on_launch = False
    settings.ui.restore_workspace = False
    application = build_application(paths=paths, settings=settings, configure_logs=False)
    application.start()
    try:
        pics = tmp_path / "pics"
        for i in range(3):
            make_jpeg(pics / f"p{i}.jpg")
        application.resolve(IndexerService).index_folder(pics)

        module = LibraryModule(application)
        module.reload()
        assert module._model.rowCount() == 3
    finally:
        application.stop()
