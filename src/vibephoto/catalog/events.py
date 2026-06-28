"""Catalog domain events.

Published on the core :class:`~vibephoto.core.events.EventBus` so the UI (and
other layers) can react to catalog changes without importing the catalog's
internals. Workers publish these from background threads; a UI adapter marshals
them onto the GUI thread.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from vibephoto.core.events import Event


@dataclass(frozen=True)
class CatalogOpened(Event):
    """A catalog file was opened or created."""

    path: Path


@dataclass(frozen=True)
class CatalogClosed(Event):
    """The active catalog was closed."""

    path: Path


@dataclass(frozen=True)
class PhotoImported(Event):
    """A photo row was added to the catalog during indexing."""

    photo_id: int
    path: Path


@dataclass(frozen=True)
class IndexProgress(Event):
    """Progress update during a folder index/sync operation."""

    folder: Path
    processed: int
    total: int


@dataclass(frozen=True)
class IndexCompleted(Event):
    """A folder index/sync finished."""

    folder: Path
    imported: int
    skipped: int
    failed: int


@dataclass(frozen=True)
class ThumbnailReady(Event):
    """A thumbnail finished generating for a photo."""

    photo_id: int
    thumbnail_path: Path
