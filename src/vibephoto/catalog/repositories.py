"""Repositories — the mapping between domain models and SQLite rows.

Each repository owns the SQL for one aggregate. They use ``Database.execute`` /
``query`` directly, so a call made *inside* a ``Database.transaction()`` block
participates in that transaction (the lock is reentrant and an explicit ``BEGIN``
suspends autocommit), while a standalone call commits on its own. This lets the
indexer batch many inserts atomically without the repositories knowing about it.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from vibephoto.catalog.database import Database
from vibephoto.catalog.models import (
    Collection,
    Folder,
    Photo,
    PhotoMetadata,
    PickStatus,
    Volume,
)


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class VolumeRepository:
    """Volumes (storage devices), keyed by stable UUID."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def get_or_create(self, uuid: str, label: str | None = None) -> Volume:
        row = self._db.query_one("SELECT * FROM volumes WHERE uuid = ?", (uuid,))
        if row is not None:
            return Volume(uuid=row["uuid"], label=row["label"], id=row["id"])
        cur = self._db.execute(
            "INSERT INTO volumes (uuid, label) VALUES (?, ?)", (uuid, label)
        )
        return Volume(uuid=uuid, label=label, id=cur.lastrowid)

    def get_by_id(self, volume_id: int) -> Volume | None:
        row = self._db.query_one("SELECT * FROM volumes WHERE id = ?", (volume_id,))
        if row is None:
            return None
        return Volume(uuid=row["uuid"], label=row["label"], id=row["id"])


class FolderRepository:
    """Folders referenced by the catalog."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def get_or_create(
        self, volume_id: int, path: str, name: str, parent_id: int | None = None
    ) -> Folder:
        row = self._db.query_one(
            "SELECT * FROM folders WHERE volume_id = ? AND path = ?", (volume_id, path)
        )
        if row is not None:
            return self._row(row)
        cur = self._db.execute(
            "INSERT INTO folders (parent_id, volume_id, path, name) VALUES (?, ?, ?, ?)",
            (parent_id, volume_id, path, name),
        )
        return Folder(
            volume_id=volume_id, path=path, name=name, parent_id=parent_id, id=cur.lastrowid
        )

    def get_by_id(self, folder_id: int) -> Folder | None:
        row = self._db.query_one("SELECT * FROM folders WHERE id = ?", (folder_id,))
        return self._row(row) if row else None

    def list_all(self) -> list[Folder]:
        return [self._row(r) for r in self._db.query("SELECT * FROM folders ORDER BY path")]

    def remove(self, folder_id: int) -> int:
        """Remove a folder and its photos from the catalog; files on disk stay.

        Returns the number of photos removed. Photo rows (and their metadata,
        develop versions, keywords, …) cascade via foreign keys; the FTS index
        has no foreign key, so its rows are cleared explicitly first.
        """
        row = self._db.query_one(
            "SELECT COUNT(*) AS n FROM photos WHERE folder_id = ?", (folder_id,)
        )
        count = int(row["n"]) if row is not None else 0
        self._db.execute(
            "DELETE FROM photo_fts WHERE rowid IN (SELECT id FROM photos WHERE folder_id = ?)",
            (folder_id,),
        )
        self._db.execute("DELETE FROM folders WHERE id = ?", (folder_id,))
        return count

    @staticmethod
    def _row(row: sqlite3.Row) -> Folder:
        return Folder(
            volume_id=row["volume_id"],
            path=row["path"],
            name=row["name"],
            parent_id=row["parent_id"],
            id=row["id"],
        )


class PhotoRepository:
    """Photos, their searchable metadata, and the FTS index."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # -- writes ------------------------------------------------------------- #

    def insert(self, photo: Photo) -> int:
        cur = self._db.execute(
            """
            INSERT INTO photos (
                folder_id, filename, file_ext, file_size, content_hash, is_raw,
                capture_time, import_time, modified_time, rating, color_label,
                pick_status, orientation, width, height, is_virtual_copy,
                master_photo_id, online, has_smart_preview
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                photo.folder_id, photo.filename, photo.file_ext, photo.file_size,
                photo.content_hash, int(photo.is_raw), _dt(photo.capture_time),
                _dt(photo.import_time), _dt(photo.modified_time), photo.rating,
                photo.color_label, int(photo.pick_status), photo.orientation,
                photo.width, photo.height, int(photo.is_virtual_copy),
                photo.master_photo_id, int(photo.online), int(photo.has_smart_preview),
            ),
        )
        photo_id = int(cur.lastrowid or 0)
        photo.id = photo_id
        self._db.execute(
            "INSERT INTO photo_fts (rowid, filename, keywords, caption, camera) "
            "VALUES (?, ?, '', '', '')",
            (photo_id, photo.filename),
        )
        return photo_id

    def set_metadata(self, meta: PhotoMetadata) -> None:
        self._db.execute(
            """
            INSERT INTO metadata (
                photo_id, camera_make, camera_model, lens, iso, aperture, shutter,
                focal_length, exposure_bias, gps_lat, gps_lon, caption, copyright, creator
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(photo_id) DO UPDATE SET
                camera_make=excluded.camera_make, camera_model=excluded.camera_model,
                lens=excluded.lens, iso=excluded.iso, aperture=excluded.aperture,
                shutter=excluded.shutter, focal_length=excluded.focal_length,
                exposure_bias=excluded.exposure_bias, gps_lat=excluded.gps_lat,
                gps_lon=excluded.gps_lon, caption=excluded.caption,
                copyright=excluded.copyright, creator=excluded.creator
            """,
            (
                meta.photo_id, meta.camera_make, meta.camera_model, meta.lens, meta.iso,
                meta.aperture, meta.shutter, meta.focal_length, meta.exposure_bias,
                meta.gps_lat, meta.gps_lon, meta.caption, meta.copyright, meta.creator,
            ),
        )
        camera = " ".join(filter(None, (meta.camera_make, meta.camera_model)))
        self._db.execute(
            "UPDATE photo_fts SET camera = ?, caption = ? WHERE rowid = ?",
            (camera, meta.caption or "", meta.photo_id),
        )

    def set_rating(self, photo_id: int, rating: int) -> None:
        self._db.execute("UPDATE photos SET rating = ? WHERE id = ?", (rating, photo_id))

    def set_color_label(self, photo_id: int, label: int) -> None:
        self._db.execute("UPDATE photos SET color_label = ? WHERE id = ?", (label, photo_id))

    def set_pick_status(self, photo_id: int, status: PickStatus) -> None:
        self._db.execute(
            "UPDATE photos SET pick_status = ? WHERE id = ?", (int(status), photo_id)
        )

    def set_online(self, photo_id: int, online: bool) -> None:
        self._db.execute("UPDATE photos SET online = ? WHERE id = ?", (int(online), photo_id))

    # -- reads -------------------------------------------------------------- #

    def get_by_id(self, photo_id: int) -> Photo | None:
        row = self._db.query_one("SELECT * FROM photos WHERE id = ?", (photo_id,))
        return self._row(row) if row else None

    def get_by_filename(self, folder_id: int, filename: str) -> Photo | None:
        row = self._db.query_one(
            "SELECT * FROM photos WHERE folder_id = ? AND filename = ? "
            "AND is_virtual_copy = 0",
            (folder_id, filename),
        )
        return self._row(row) if row else None

    def list_by_folder(self, folder_id: int) -> list[Photo]:
        rows = self._db.query(
            "SELECT * FROM photos WHERE folder_id = ? ORDER BY capture_time, filename",
            (folder_id,),
        )
        return [self._row(r) for r in rows]

    def list_all(self, limit: int = 5000) -> list[Photo]:
        """All non-virtual photos, newest captures first (for the library grid)."""
        rows = self._db.query(
            "SELECT * FROM photos WHERE is_virtual_copy = 0 "
            "ORDER BY capture_time DESC, filename LIMIT ?",
            (limit,),
        )
        return [self._row(r) for r in rows]

    def get_metadata(self, photo_id: int) -> PhotoMetadata | None:
        row = self._db.query_one("SELECT * FROM metadata WHERE photo_id = ?", (photo_id,))
        if row is None:
            return None
        return PhotoMetadata(
            photo_id=row["photo_id"], camera_make=row["camera_make"],
            camera_model=row["camera_model"], lens=row["lens"], iso=row["iso"],
            aperture=row["aperture"], shutter=row["shutter"],
            focal_length=row["focal_length"], exposure_bias=row["exposure_bias"],
            gps_lat=row["gps_lat"], gps_lon=row["gps_lon"], caption=row["caption"],
            copyright=row["copyright"], creator=row["creator"],
        )

    def count(self) -> int:
        row = self._db.query_one("SELECT COUNT(*) AS n FROM photos")
        return int(row["n"]) if row else 0

    def search(self, text: str, limit: int = 500) -> list[Photo]:
        """Full-text search over filename/keywords/caption/camera via FTS5."""
        rows = self._db.query(
            "SELECT p.* FROM photos p JOIN photo_fts f ON f.rowid = p.id "
            "WHERE photo_fts MATCH ? ORDER BY rank LIMIT ?",
            (text, limit),
        )
        return [self._row(r) for r in rows]

    @staticmethod
    def _row(row: sqlite3.Row) -> Photo:
        return Photo(
            folder_id=row["folder_id"], filename=row["filename"], file_ext=row["file_ext"],
            import_time=_parse_dt(row["import_time"]) or datetime.min,
            file_size=row["file_size"], content_hash=row["content_hash"],
            is_raw=bool(row["is_raw"]), capture_time=_parse_dt(row["capture_time"]),
            modified_time=_parse_dt(row["modified_time"]), rating=row["rating"],
            color_label=row["color_label"], pick_status=PickStatus(row["pick_status"]),
            orientation=row["orientation"], width=row["width"], height=row["height"],
            is_virtual_copy=bool(row["is_virtual_copy"]),
            master_photo_id=row["master_photo_id"], online=bool(row["online"]),
            has_smart_preview=bool(row["has_smart_preview"]), id=row["id"],
        )


class CollectionRepository:
    """Standard and smart collections."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def create(self, collection: Collection) -> int:
        cur = self._db.execute(
            "INSERT INTO collections (parent_id, name, kind) VALUES (?, ?, ?)",
            (collection.parent_id, collection.name, collection.kind),
        )
        collection.id = int(cur.lastrowid or 0)
        return collection.id

    def add_photo(self, collection_id: int, photo_id: int, sort_order: int | None = None) -> None:
        self._db.execute(
            "INSERT OR IGNORE INTO collection_photos (collection_id, photo_id, sort_order) "
            "VALUES (?, ?, ?)",
            (collection_id, photo_id, sort_order),
        )

    def list_all(self) -> list[Collection]:
        rows = self._db.query("SELECT * FROM collections ORDER BY name")
        return [
            Collection(name=r["name"], kind=r["kind"], parent_id=r["parent_id"], id=r["id"])
            for r in rows
        ]

    def photo_ids(self, collection_id: int) -> list[int]:
        rows = self._db.query(
            "SELECT photo_id FROM collection_photos WHERE collection_id = ? "
            "ORDER BY sort_order, photo_id",
            (collection_id,),
        )
        return [r["photo_id"] for r in rows]
