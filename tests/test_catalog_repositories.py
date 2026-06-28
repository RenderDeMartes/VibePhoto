"""Tests for catalog repositories (folders, photos, metadata, FTS, collections)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from vibephoto.catalog.database import Database
from vibephoto.catalog.models import (
    Collection,
    Photo,
    PhotoMetadata,
    PickStatus,
)
from vibephoto.catalog.repositories import (
    CollectionRepository,
    FolderRepository,
    PhotoRepository,
    VolumeRepository,
)


@pytest.fixture
def db(tmp_path: Path) -> Database:
    return Database(tmp_path / "c.vibephoto")


def _make_photo(folder_id: int, filename: str = "IMG_0001.JPG") -> Photo:
    return Photo(
        folder_id=folder_id,
        filename=filename,
        file_ext="jpg",
        import_time=datetime(2024, 1, 15, 10, 0, 0),
        file_size=12345,
        content_hash="1:abc",
        capture_time=datetime(2024, 1, 15, 9, 30, 0),
        width=800,
        height=600,
    )


def test_volume_get_or_create_is_stable(db: Database) -> None:
    repo = VolumeRepository(db)
    v1 = repo.get_or_create("uuid-1", "Card")
    v2 = repo.get_or_create("uuid-1", "Card")
    assert v1.id == v2.id


def test_folder_get_or_create(db: Database) -> None:
    vol = VolumeRepository(db).get_or_create("uuid-1")
    repo = FolderRepository(db)
    f1 = repo.get_or_create(vol.id, "shoots/2024", "2024")
    f2 = repo.get_or_create(vol.id, "shoots/2024", "2024")
    assert f1.id == f2.id
    assert len(repo.list_all()) == 1


def test_insert_and_get_photo(db: Database) -> None:
    vol = VolumeRepository(db).get_or_create("uuid-1")
    folder = FolderRepository(db).get_or_create(vol.id, "p", "p")
    repo = PhotoRepository(db)
    pid = repo.insert(_make_photo(folder.id))
    assert pid > 0
    fetched = repo.get_by_id(pid)
    assert fetched is not None
    assert fetched.filename == "IMG_0001.JPG"
    assert fetched.width == 800
    assert fetched.capture_time == datetime(2024, 1, 15, 9, 30, 0)


def test_get_by_filename_for_diff(db: Database) -> None:
    vol = VolumeRepository(db).get_or_create("uuid-1")
    folder = FolderRepository(db).get_or_create(vol.id, "p", "p")
    repo = PhotoRepository(db)
    repo.insert(_make_photo(folder.id, "A.JPG"))
    assert repo.get_by_filename(folder.id, "A.JPG") is not None
    assert repo.get_by_filename(folder.id, "B.JPG") is None


def test_metadata_roundtrip(db: Database) -> None:
    vol = VolumeRepository(db).get_or_create("uuid-1")
    folder = FolderRepository(db).get_or_create(vol.id, "p", "p")
    repo = PhotoRepository(db)
    pid = repo.insert(_make_photo(folder.id))
    repo.set_metadata(
        PhotoMetadata(photo_id=pid, camera_make="Canon", camera_model="EOS R5", iso=400)
    )
    meta = repo.get_metadata(pid)
    assert meta is not None
    assert meta.camera_model == "EOS R5"
    assert meta.iso == 400


def test_set_metadata_upserts(db: Database) -> None:
    vol = VolumeRepository(db).get_or_create("uuid-1")
    folder = FolderRepository(db).get_or_create(vol.id, "p", "p")
    repo = PhotoRepository(db)
    pid = repo.insert(_make_photo(folder.id))
    repo.set_metadata(PhotoMetadata(photo_id=pid, iso=100))
    repo.set_metadata(PhotoMetadata(photo_id=pid, iso=800))  # update, not duplicate
    assert repo.get_metadata(pid).iso == 800


def test_library_actions(db: Database) -> None:
    vol = VolumeRepository(db).get_or_create("uuid-1")
    folder = FolderRepository(db).get_or_create(vol.id, "p", "p")
    repo = PhotoRepository(db)
    pid = repo.insert(_make_photo(folder.id))
    repo.set_rating(pid, 4)
    repo.set_color_label(pid, 2)
    repo.set_pick_status(pid, PickStatus.PICKED)
    p = repo.get_by_id(pid)
    assert (p.rating, p.color_label, p.pick_status) == (4, 2, PickStatus.PICKED)


def test_fts_search_by_filename(db: Database) -> None:
    vol = VolumeRepository(db).get_or_create("uuid-1")
    folder = FolderRepository(db).get_or_create(vol.id, "p", "p")
    repo = PhotoRepository(db)
    repo.insert(_make_photo(folder.id, "beach_sunset.jpg"))
    repo.insert(_make_photo(folder.id, "mountain.jpg"))
    hits = repo.search("beach")
    assert len(hits) == 1
    assert hits[0].filename == "beach_sunset.jpg"


def test_fts_search_by_camera(db: Database) -> None:
    vol = VolumeRepository(db).get_or_create("uuid-1")
    folder = FolderRepository(db).get_or_create(vol.id, "p", "p")
    repo = PhotoRepository(db)
    pid = repo.insert(_make_photo(folder.id, "x.jpg"))
    repo.set_metadata(PhotoMetadata(photo_id=pid, camera_make="Nikon", camera_model="Z9"))
    assert len(repo.search("Nikon")) == 1


def test_count(db: Database) -> None:
    vol = VolumeRepository(db).get_or_create("uuid-1")
    folder = FolderRepository(db).get_or_create(vol.id, "p", "p")
    repo = PhotoRepository(db)
    assert repo.count() == 0
    repo.insert(_make_photo(folder.id, "a.jpg"))
    repo.insert(_make_photo(folder.id, "b.jpg"))
    assert repo.count() == 2


def test_collections(db: Database) -> None:
    vol = VolumeRepository(db).get_or_create("uuid-1")
    folder = FolderRepository(db).get_or_create(vol.id, "p", "p")
    photos = PhotoRepository(db)
    pid = photos.insert(_make_photo(folder.id))
    coll = CollectionRepository(db)
    cid = coll.create(Collection(name="Best Of"))
    coll.add_photo(cid, pid)
    coll.add_photo(cid, pid)  # idempotent
    assert coll.photo_ids(cid) == [pid]
    assert len(coll.list_all()) == 1
