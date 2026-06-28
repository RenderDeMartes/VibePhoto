"""Tests for CatalogService lifecycle, backup, optimize, repair, and events."""

from __future__ import annotations

from pathlib import Path

import pytest

from vibephoto.catalog.events import CatalogClosed, CatalogOpened
from vibephoto.catalog.service import CatalogError, CatalogService
from vibephoto.core.config import CatalogSettings
from vibephoto.core.events import EventBus
from vibephoto.core.paths import AppPaths


@pytest.fixture
def service(tmp_path: Path) -> CatalogService:
    paths = AppPaths.under(tmp_path).ensure()
    settings = CatalogSettings(backup_on_launch=False, max_backups=2)
    return CatalogService(paths, settings, EventBus())


def test_start_opens_default_catalog(service: CatalogService) -> None:
    service.start()
    assert service.is_open
    assert service.photos.count() == 0
    service.stop()
    assert not service.is_open


def test_open_publishes_events(tmp_path: Path) -> None:
    paths = AppPaths.under(tmp_path).ensure()
    bus = EventBus()
    opened: list[CatalogOpened] = []
    closed: list[CatalogClosed] = []
    bus.subscribe(CatalogOpened, opened.append)
    bus.subscribe(CatalogClosed, closed.append)
    svc = CatalogService(paths, CatalogSettings(backup_on_launch=False), bus)
    svc.open(tmp_path / "my.vibephoto")
    svc.close()
    assert len(opened) == 1 and len(closed) == 1


def test_accessing_repos_without_open_raises(service: CatalogService) -> None:
    with pytest.raises(CatalogError):
        _ = service.photos


def test_backup_creates_file_and_prunes(service: CatalogService) -> None:
    service.start()
    b1 = service.backup()
    service.backup()
    b3 = service.backup()
    assert b3.exists()
    # max_backups=2: only the two newest remain.
    backups_dir = b1.parent
    remaining = list(backups_dir.glob("*.vibephoto"))
    assert len(remaining) == 2
    service.stop()


def test_optimize_and_repair(service: CatalogService) -> None:
    service.start()
    service.optimize()  # must not raise
    assert service.repair() is True
    service.stop()


def test_reopen_persists_data(tmp_path: Path) -> None:
    paths = AppPaths.under(tmp_path).ensure()
    settings = CatalogSettings(backup_on_launch=False)
    path = tmp_path / "persist.vibephoto"

    svc1 = CatalogService(paths, settings, EventBus())
    svc1.open(path)
    vol = svc1.volumes.get_or_create("uuid-1", "Disk")
    svc1.folders.get_or_create(vol.id, "p", "p")
    svc1.close()

    svc2 = CatalogService(paths, settings, EventBus())
    svc2.open(path)
    assert len(svc2.folders.list_all()) == 1
    svc2.close()
