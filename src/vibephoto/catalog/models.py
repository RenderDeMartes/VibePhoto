"""Catalog domain models.

Plain, typed records that move between the repositories, services, and (via
view-models) the UI. They are intentionally free of persistence logic — mapping
to/from SQLite rows lives in the repositories — so the domain stays testable and
the storage layer can evolve independently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum


class PickStatus(IntEnum):
    """professional pick flag."""

    REJECTED = -1
    NONE = 0
    PICKED = 1


@dataclass(slots=True)
class Volume:
    """A storage volume, identified by a stable UUID so relinking survives
    drive-letter / mount-point changes."""

    uuid: str
    label: str | None = None
    id: int | None = None


@dataclass(slots=True)
class Folder:
    """A folder on a volume, referenced by the catalog (path relative to volume)."""

    volume_id: int
    path: str
    name: str
    parent_id: int | None = None
    id: int | None = None


@dataclass(slots=True)
class Photo:
    """A master image (or virtual copy) tracked by the catalog.

    ``id`` is ``None`` until persisted. Timestamps are timezone-naive ISO strings
    in the DB but exposed here as :class:`datetime` for ergonomic use.
    """

    folder_id: int
    filename: str
    file_ext: str
    import_time: datetime
    file_size: int | None = None
    content_hash: str | None = None
    is_raw: bool = False
    capture_time: datetime | None = None
    modified_time: datetime | None = None
    rating: int = 0
    color_label: int = 0
    pick_status: PickStatus = PickStatus.NONE
    orientation: int = 1
    width: int | None = None
    height: int | None = None
    is_virtual_copy: bool = False
    master_photo_id: int | None = None
    online: bool = True
    has_smart_preview: bool = False
    id: int | None = None


@dataclass(slots=True)
class PhotoMetadata:
    """Searchable EXIF/IPTC fields for a photo (1:1 with :class:`Photo`)."""

    photo_id: int
    camera_make: str | None = None
    camera_model: str | None = None
    lens: str | None = None
    iso: int | None = None
    aperture: float | None = None
    shutter: float | None = None
    focal_length: float | None = None
    exposure_bias: float | None = None
    gps_lat: float | None = None
    gps_lon: float | None = None
    caption: str | None = None
    copyright: str | None = None
    creator: str | None = None


@dataclass(slots=True)
class Collection:
    """A standard or smart collection (organisational grouping)."""

    name: str
    kind: str = "standard"  # "standard" | "smart"
    parent_id: int | None = None
    id: int | None = None


@dataclass(slots=True)
class SmartRule:
    """A single predicate in a smart collection's rule tree."""

    field: str
    op: str  # "=", "!=", ">", ">=", "<", "<=", "contains", "startswith"
    value: object


@dataclass(slots=True)
class SmartQuery:
    """A smart collection's rule set (``match`` = how predicates combine)."""

    match: str = "all"  # "all" | "any"
    rules: list[SmartRule] = field(default_factory=list)
