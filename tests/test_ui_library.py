"""GUI tests for Library star ratings and the rating filter."""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QItemSelectionModel, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from vibephoto.app.bootstrap import build_application
from vibephoto.catalog.indexer import IndexerService
from vibephoto.catalog.service import CatalogService
from vibephoto.core.config import AppSettings
from vibephoto.core.paths import AppPaths
from vibephoto.ui.module_views import LibraryModule
from vibephoto.ui.photo_grid import RATING_ROLE

pytestmark = pytest.mark.gui


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def library(tmp_path, make_jpeg):
    paths = AppPaths.under(tmp_path / "app").ensure()
    settings = AppSettings()
    settings.catalog.backup_on_launch = False
    settings.ui.restore_workspace = False
    app = build_application(paths=paths, settings=settings, configure_logs=False)
    app.start()
    pics = tmp_path / "pics"
    for i in range(4):
        make_jpeg(pics / f"p{i}.jpg")
    app.resolve(IndexerService).index_folder(pics)
    module = LibraryModule(app)
    module.reload()
    yield module, app
    app.stop()


def _select_rows(module: LibraryModule, *rows: int) -> None:
    selection = module._grid.selectionModel()
    selection.clearSelection()
    for row in rows:
        selection.select(module._model.index(row, 0), QItemSelectionModel.SelectionFlag.Select)


def test_apply_rating_persists_and_shows(qapp: QApplication, library) -> None:
    module, app = library
    module._grid.selectAll()
    module._apply_rating(3)

    assert all(p.rating == 3 for p in app.resolve(CatalogService).photos.list_all())
    assert module._model.data(module._model.index(0, 0), RATING_ROLE) == 3


def test_number_key_emits_rating(qapp: QApplication, library) -> None:
    module, _ = library
    captured: list[int] = []
    module._grid.rating_key.connect(captured.append)
    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_4, Qt.KeyboardModifier.NoModifier)
    module._grid.keyPressEvent(event)
    assert captured == [4]


def test_filter_by_minimum_rating(qapp: QApplication, library) -> None:
    module, _ = library
    _select_rows(module, 0, 1)
    module._apply_rating(5)  # two photos at 5 stars, two unrated

    assert len(module.current_photos()) == 4  # no filter yet
    module.set_min_rating(5)
    visible = module.current_photos()
    assert len(visible) == 2
    assert all(p.rating >= 5 for p in visible)
    module.set_min_rating(0)
    assert len(module.current_photos()) == 4


def test_zero_key_clears_rating(qapp: QApplication, library) -> None:
    module, app = library
    module._grid.selectAll()
    module._apply_rating(2)
    assert all(p.rating == 2 for p in module.current_photos())
    module._apply_rating(0)
    assert all(p.rating == 0 for p in app.resolve(CatalogService).photos.list_all())
