"""Integration tests: catalog + indexer + metadata end to end."""

from __future__ import annotations

from pathlib import Path

import pytest

from vibephoto.app.bootstrap import build_application
from vibephoto.catalog.events import IndexCompleted, PhotoImported
from vibephoto.catalog.indexer import IndexerService
from vibephoto.catalog.service import CatalogService
from vibephoto.core.config import AppSettings
from vibephoto.core.paths import AppPaths

pytestmark = pytest.mark.integration


@pytest.fixture
def app(tmp_path: Path):
    paths = AppPaths.under(tmp_path / "app").ensure()
    settings = AppSettings()
    settings.catalog.backup_on_launch = False
    application = build_application(paths=paths, settings=settings, configure_logs=False)
    application.start()
    yield application
    application.stop()


def _make_photos(make_jpeg, folder: Path, n: int) -> None:
    for i in range(n):
        make_jpeg(folder / f"IMG_{i:04d}.jpg", model=f"Model{i % 2}")


def test_index_imports_photos_with_metadata(app, make_jpeg, tmp_path: Path) -> None:
    photos_dir = tmp_path / "photos"
    _make_photos(make_jpeg, photos_dir, 5)

    indexer = app.resolve(IndexerService)
    catalog = app.resolve(CatalogService)

    result = indexer.index_folder(photos_dir)
    assert result.imported == 5
    assert result.failed == 0
    assert catalog.photos.count() == 5

    # Metadata captured for an imported photo.
    folder = catalog.folders.list_all()[0]
    photo = catalog.photos.list_by_folder(folder.id)[0]
    meta = catalog.photos.get_metadata(photo.id)
    assert meta is not None and meta.camera_make == "Canon"
    assert photo.width == 800 and photo.height == 600


def test_index_is_incremental(app, make_jpeg, tmp_path: Path) -> None:
    photos_dir = tmp_path / "photos"
    _make_photos(make_jpeg, photos_dir, 3)
    indexer = app.resolve(IndexerService)
    catalog = app.resolve(CatalogService)

    first = indexer.index_folder(photos_dir)
    assert first.imported == 3

    # Re-run with no changes: everything skipped.
    second = indexer.index_folder(photos_dir)
    assert second.imported == 0
    assert second.skipped == 3

    # Add one more, re-run: only the new file imports.
    make_jpeg(photos_dir / "IMG_9999.jpg")
    third = indexer.index_folder(photos_dir)
    assert third.imported == 1
    assert catalog.photos.count() == 4


def test_index_publishes_events(app, make_jpeg, tmp_path: Path) -> None:
    photos_dir = tmp_path / "photos"
    _make_photos(make_jpeg, photos_dir, 4)

    imported_ids: list[int] = []
    completed: list[IndexCompleted] = []
    app.events.subscribe(PhotoImported, lambda e: imported_ids.append(e.photo_id))
    app.events.subscribe(IndexCompleted, completed.append)

    app.resolve(IndexerService).index_folder(photos_dir)

    assert len(imported_ids) == 4
    assert len(completed) == 1
    assert completed[0].imported == 4


def test_index_recurses_subfolders(app, make_jpeg, tmp_path: Path) -> None:
    root = tmp_path / "photos"
    make_jpeg(root / "a.jpg")
    make_jpeg(root / "sub" / "b.jpg")
    make_jpeg(root / "sub" / "deeper" / "c.jpg")

    result = app.resolve(IndexerService).index_folder(root, recursive=True)
    assert result.imported == 3


def test_unsupported_files_ignored(app, make_jpeg, tmp_path: Path) -> None:
    photos_dir = tmp_path / "photos"
    make_jpeg(photos_dir / "a.jpg")
    (photos_dir / "notes.txt").write_text("ignore me")
    (photos_dir / "video.mp4").write_bytes(b"\x00\x00")

    result = app.resolve(IndexerService).index_folder(photos_dir)
    assert result.imported == 1
