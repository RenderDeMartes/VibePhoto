"""Catalog database schema and forward-only migrations.

The schema is defined as a sequence of migration steps keyed by version. The
catalog's ``PRAGMA user_version`` records the applied version; :func:`migrate`
applies any pending steps inside a single transaction. This gives deterministic,
auditable upgrades and lets the schema grow across phases without ad-hoc DDL
scattered through the code.

See ``docs/04-database-schema.md`` for the rationale behind each table.
"""

from __future__ import annotations

import sqlite3
from typing import Final

#: The schema version this build expects. Bump when adding a migration.
SCHEMA_VERSION: Final = 1

# --- Migration 1: initial schema ------------------------------------------- #
_MIGRATION_1: Final = """
CREATE TABLE schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE volumes (
    id         INTEGER PRIMARY KEY,
    uuid       TEXT UNIQUE NOT NULL,
    label      TEXT,
    last_mount TEXT
);

CREATE TABLE folders (
    id        INTEGER PRIMARY KEY,
    parent_id INTEGER REFERENCES folders(id) ON DELETE CASCADE,
    volume_id INTEGER NOT NULL REFERENCES volumes(id),
    path      TEXT NOT NULL,
    name      TEXT NOT NULL,
    UNIQUE(volume_id, path)
);
CREATE INDEX idx_folders_parent ON folders(parent_id);

CREATE TABLE photos (
    id                INTEGER PRIMARY KEY,
    folder_id         INTEGER NOT NULL REFERENCES folders(id) ON DELETE CASCADE,
    filename          TEXT NOT NULL,
    file_ext          TEXT NOT NULL,
    file_size         INTEGER,
    content_hash      TEXT,
    is_raw            INTEGER NOT NULL DEFAULT 0,
    capture_time      TEXT,
    import_time       TEXT NOT NULL,
    modified_time     TEXT,
    rating            INTEGER NOT NULL DEFAULT 0,
    color_label       INTEGER NOT NULL DEFAULT 0,
    pick_status       INTEGER NOT NULL DEFAULT 0,
    orientation       INTEGER NOT NULL DEFAULT 1,
    width             INTEGER,
    height            INTEGER,
    is_virtual_copy   INTEGER NOT NULL DEFAULT 0,
    master_photo_id   INTEGER REFERENCES photos(id) ON DELETE CASCADE,
    online            INTEGER NOT NULL DEFAULT 1,
    has_smart_preview INTEGER NOT NULL DEFAULT 0,
    UNIQUE(folder_id, filename, is_virtual_copy, master_photo_id)
);
CREATE INDEX idx_photos_folder  ON photos(folder_id);
CREATE INDEX idx_photos_capture ON photos(capture_time);
CREATE INDEX idx_photos_rating  ON photos(rating);
CREATE INDEX idx_photos_label   ON photos(color_label);
CREATE INDEX idx_photos_hash    ON photos(content_hash);

CREATE TABLE metadata (
    photo_id      INTEGER PRIMARY KEY REFERENCES photos(id) ON DELETE CASCADE,
    camera_make   TEXT,
    camera_model  TEXT,
    lens          TEXT,
    iso           INTEGER,
    aperture      REAL,
    shutter       REAL,
    focal_length  REAL,
    exposure_bias REAL,
    gps_lat       REAL,
    gps_lon       REAL,
    caption       TEXT,
    copyright     TEXT,
    creator       TEXT
);
CREATE INDEX idx_metadata_camera ON metadata(camera_model);
CREATE INDEX idx_metadata_iso    ON metadata(iso);

CREATE TABLE develop_versions (
    id              INTEGER PRIMARY KEY,
    photo_id        INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    name            TEXT,
    is_current      INTEGER NOT NULL DEFAULT 1,
    graph_json      TEXT NOT NULL,
    process_version TEXT NOT NULL,
    created_time    TEXT NOT NULL,
    updated_time    TEXT NOT NULL
);
CREATE INDEX idx_develop_photo ON develop_versions(photo_id, is_current);

CREATE TABLE keywords (
    id        INTEGER PRIMARY KEY,
    parent_id INTEGER REFERENCES keywords(id) ON DELETE CASCADE,
    name      TEXT NOT NULL,
    UNIQUE(parent_id, name)
);
CREATE TABLE photo_keywords (
    photo_id   INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    keyword_id INTEGER NOT NULL REFERENCES keywords(id) ON DELETE CASCADE,
    PRIMARY KEY (photo_id, keyword_id)
);

CREATE TABLE collections (
    id        INTEGER PRIMARY KEY,
    parent_id INTEGER REFERENCES collections(id) ON DELETE CASCADE,
    name      TEXT NOT NULL,
    kind      TEXT NOT NULL DEFAULT 'standard'
);
CREATE TABLE collection_photos (
    collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    photo_id      INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    sort_order    INTEGER,
    PRIMARY KEY (collection_id, photo_id)
);
CREATE TABLE smart_collections (
    collection_id INTEGER PRIMARY KEY REFERENCES collections(id) ON DELETE CASCADE,
    rules_json    TEXT NOT NULL,
    match_type    TEXT NOT NULL DEFAULT 'all'
);

CREATE TABLE presets (
    id          INTEGER PRIMARY KEY,
    uuid        TEXT UNIQUE NOT NULL,
    folder      TEXT,
    name        TEXT NOT NULL,
    graph_json  TEXT NOT NULL,
    source      TEXT,
    is_favorite INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE preset_usage (
    id        INTEGER PRIMARY KEY,
    photo_id  INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    preset_id INTEGER REFERENCES presets(id) ON DELETE SET NULL,
    ts        TEXT NOT NULL
);

CREATE TABLE exports (
    id        INTEGER PRIMARY KEY,
    photo_id  INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    preset    TEXT,
    dest_path TEXT,
    fmt       TEXT,
    width     INTEGER,
    height    INTEGER,
    ts        TEXT NOT NULL,
    status    TEXT
);

CREATE TABLE hdr_groups (
    id              INTEGER PRIMARY KEY,
    result_photo_id INTEGER REFERENCES photos(id) ON DELETE SET NULL,
    created_time    TEXT NOT NULL,
    params_json     TEXT
);
CREATE TABLE hdr_group_members (
    group_id INTEGER NOT NULL REFERENCES hdr_groups(id) ON DELETE CASCADE,
    photo_id INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    ev       REAL,
    PRIMARY KEY (group_id, photo_id)
);

CREATE VIRTUAL TABLE photo_fts USING fts5(
    filename, keywords, caption, camera,
    tokenize='unicode61'
);
"""

#: version -> DDL. Applied in ascending order for any version above the current.
MIGRATIONS: Final[dict[int, str]] = {
    1: _MIGRATION_1,
}


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations to ``conn``; return the resulting schema version.

    Idempotent: re-running on an up-to-date database does nothing. Each step runs
    inside a transaction so a failure leaves the catalog at its prior version.
    """
    current = int(conn.execute("PRAGMA user_version").fetchone()[0])
    target = SCHEMA_VERSION
    if current >= target:
        return current

    for version in range(current + 1, target + 1):
        ddl = MIGRATIONS.get(version)
        if ddl is None:
            raise RuntimeError(f"Missing migration for schema version {version}")
        with conn:  # transaction: commit on success, rollback on exception
            conn.executescript(ddl)
            # PRAGMA cannot be parameterised; version is an int we control.
            conn.execute(f"PRAGMA user_version = {version}")
    return target
