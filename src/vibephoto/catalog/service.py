"""CatalogService — opens/owns a catalog and exposes its repositories.

Implements the core :class:`~vibephoto.core.lifecycle.Service` protocol so the
application's :class:`ServiceHost` starts it on launch and closes it (checkpointing
the WAL) on shutdown. On start it opens — creating if necessary — the default
catalog, optionally backing it up first per :class:`CatalogSettings`.

All catalog access in the app goes through this service's repositories, which keeps
the single-writer ``Database`` instance and the open/close lifecycle in one place.
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path

from vibephoto.catalog.database import Database
from vibephoto.catalog.events import CatalogClosed, CatalogOpened
from vibephoto.catalog.models import Photo
from vibephoto.catalog.repositories import (
    CollectionRepository,
    FolderRepository,
    PhotoRepository,
    VolumeRepository,
)
from vibephoto.core.config import CatalogSettings
from vibephoto.core.errors import VibePhotoError
from vibephoto.core.events import EventBus
from vibephoto.core.paths import AppPaths

logger = logging.getLogger(__name__)

CATALOG_SUFFIX = ".vibephoto"


class CatalogError(VibePhotoError):
    """Raised on catalog open/create/repair failures."""

    code = "vibephoto.catalog"


class CatalogService:
    """Lifecycle-managed owner of the active catalog."""

    def __init__(
        self,
        paths: AppPaths,
        settings: CatalogSettings,
        event_bus: EventBus,
    ) -> None:
        self._paths = paths
        self._settings = settings
        self._events = event_bus
        self._db: Database | None = None
        self._photos: PhotoRepository | None = None
        self._folders: FolderRepository | None = None
        self._volumes: VolumeRepository | None = None
        self._collections: CollectionRepository | None = None

    # -- Service protocol --------------------------------------------------- #

    @property
    def name(self) -> str:
        return "catalog"

    def start(self) -> None:
        default = self._paths.catalogs_dir / f"default{CATALOG_SUFFIX}"
        if default.exists() and self._settings.backup_on_launch:
            try:
                self.backup(default)
            except OSError:
                logger.warning("Launch backup failed for %s", default, exc_info=True)
        self.open(default)

    def stop(self) -> None:
        self.close()

    # -- Catalog operations ------------------------------------------------- #

    def open(self, path: Path) -> None:
        """Open (creating if needed) the catalog at ``path``."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if self._db is not None:
            self.close()
        try:
            self._db = Database(path)
        except Exception as exc:
            raise CatalogError(
                f"Failed to open catalog {path}: {exc}", context={"path": str(path)}
            ) from exc
        self._photos = PhotoRepository(self._db)
        self._folders = FolderRepository(self._db)
        self._volumes = VolumeRepository(self._db)
        self._collections = CollectionRepository(self._db)
        self._events.publish(CatalogOpened(path=path))
        logger.info("Catalog active: %s", path)

    def close(self) -> None:
        """Close the active catalog (no-op if none open)."""
        if self._db is None:
            return
        path = self._db.path
        self._db.close()
        self._db = None
        self._photos = self._folders = self._volumes = self._collections = None
        self._events.publish(CatalogClosed(path=path))

    def backup(self, path: Path | None = None) -> Path:
        """Write a timestamped backup copy; prune to ``max_backups``. Returns it."""
        source = Path(path) if path is not None else self._require_db().path
        if self._db is not None and self._db.path == source:
            self._db.checkpoint()
        backups_dir = self._paths.data_dir / "backups"
        backups_dir.mkdir(parents=True, exist_ok=True)
        # Timestamp the name, but never overwrite: Windows' clock can have ~15 ms
        # resolution, so rapid backups can share a microsecond stamp — disambiguate
        # with a counter so each backup is a distinct file.
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        dest = backups_dir / f"{source.stem}-{stamp}{CATALOG_SUFFIX}"
        counter = 1
        while dest.exists():
            dest = backups_dir / f"{source.stem}-{stamp}-{counter}{CATALOG_SUFFIX}"
            counter += 1
        shutil.copy2(source, dest)
        self._prune_backups(backups_dir, source.stem)
        logger.info("Catalog backup written: %s", dest)
        return dest

    def resolve_path(self, photo: Photo) -> Path | None:
        """Reconstruct a photo's absolute filesystem path from volume + folder.

        Returns ``None`` if the owning folder/volume cannot be found. The volume's
        anchor (drive/mount root) is recombined with the folder's volume-relative
        path and the filename.
        """
        if photo.folder_id is None:
            return None
        folder = self.folders.get_by_id(photo.folder_id)
        if folder is None:
            return None
        volume = self.volumes.get_by_id(folder.volume_id)
        anchor = volume.label if volume and volume.label else ""
        return Path(anchor) / folder.path / photo.filename

    def optimize(self) -> None:
        """Run ANALYZE + VACUUM on the active catalog."""
        self._require_db().optimize()

    def repair(self) -> bool:
        """Run an integrity check; return True if the catalog is healthy."""
        ok = self._require_db().integrity_ok()
        if not ok:
            logger.error("Integrity check failed for %s", self._require_db().path)
        return ok

    def _prune_backups(self, backups_dir: Path, stem: str) -> None:
        # Sort by filename, not mtime: ``copy2`` preserves the source's mtime, so
        # every backup shares the catalog's timestamp. The name embeds a
        # microsecond stamp, giving true creation order (newest first).
        backups = sorted(
            backups_dir.glob(f"{stem}-*{CATALOG_SUFFIX}"),
            reverse=True,
        )
        for old in backups[self._settings.max_backups :]:
            old.unlink(missing_ok=True)

    # -- Repository accessors ----------------------------------------------- #

    @property
    def is_open(self) -> bool:
        return self._db is not None

    @property
    def db(self) -> Database:
        return self._require_db()

    @property
    def photos(self) -> PhotoRepository:
        if self._photos is None:
            raise CatalogError("No catalog is open")
        return self._photos

    @property
    def folders(self) -> FolderRepository:
        if self._folders is None:
            raise CatalogError("No catalog is open")
        return self._folders

    @property
    def volumes(self) -> VolumeRepository:
        if self._volumes is None:
            raise CatalogError("No catalog is open")
        return self._volumes

    @property
    def collections(self) -> CollectionRepository:
        if self._collections is None:
            raise CatalogError("No catalog is open")
        return self._collections

    def _require_db(self) -> Database:
        if self._db is None:
            raise CatalogError("No catalog is open")
        return self._db
