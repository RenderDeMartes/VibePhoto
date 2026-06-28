"""Catalog layer — the SQLite-backed library of photos and their organisation.

Owns the catalog database (folders, photos, collections, smart collections,
keywords, ratings/labels/flags, edit history, preset usage, export history),
sidecar (XMP) synchronisation, and incremental indexing of the filesystem.

Depends on: ``core``, ``metadata``. Never imports ``ui``.
Designed in: ``docs/04-database-schema.md`` and ``docs/05-catalog-architecture.md``.
Built in: Phase 2.
"""

from __future__ import annotations

from vibephoto.catalog.database import Database
from vibephoto.catalog.models import (
    Collection,
    Folder,
    Photo,
    PhotoMetadata,
    PickStatus,
    SmartQuery,
    SmartRule,
    Volume,
)
from vibephoto.catalog.service import CatalogError, CatalogService

__all__ = [
    "CatalogError",
    "CatalogService",
    "Collection",
    "Database",
    "Folder",
    "Photo",
    "PhotoMetadata",
    "PickStatus",
    "SmartQuery",
    "SmartRule",
    "Volume",
]
