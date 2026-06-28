# 04 — Database Schema Design

## 1. Engine & pragmas

- **SQLite** (one file per catalog, extension `.vibephoto`).
- `PRAGMA journal_mode=WAL` — concurrent readers + one writer; crash-safe.
- `PRAGMA foreign_keys=ON`, `synchronous=NORMAL` (safe with WAL), `busy_timeout`.
- **FTS5** virtual table for full-text search over filename/keywords/caption.
- A `schema_version` row drives forward-only migrations.

**Why SQLite:** zero-admin single-file catalogs are exactly the professional RAW editors model;
transactional integrity protects edits; FTS5 + good indexes meet the <200 ms
search target at 100k+ rows. **Tradeoff:** single-writer (mitigated by WAL +
serialised writes) and no built-in multi-user (a deliberate v1 non-goal).

## 2. Core tables (DDL sketch)

```sql
CREATE TABLE schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);  -- ('schema_version', '1'), ('app_version', '0.1.0'), ('catalog_uuid', …)

-- Filesystem volumes, so relinking survives drive-letter / mount changes.
CREATE TABLE volumes (
    id          INTEGER PRIMARY KEY,
    uuid        TEXT UNIQUE NOT NULL,
    label       TEXT,
    last_mount  TEXT
);

CREATE TABLE folders (
    id          INTEGER PRIMARY KEY,
    parent_id   INTEGER REFERENCES folders(id) ON DELETE CASCADE,
    volume_id   INTEGER NOT NULL REFERENCES volumes(id),
    path        TEXT NOT NULL,          -- relative to the volume root
    name        TEXT NOT NULL,
    UNIQUE(volume_id, path)
);
CREATE INDEX idx_folders_parent ON folders(parent_id);

-- One row per master image file on disk.
CREATE TABLE photos (
    id              INTEGER PRIMARY KEY,
    folder_id       INTEGER NOT NULL REFERENCES folders(id) ON DELETE CASCADE,
    filename        TEXT NOT NULL,
    file_ext        TEXT NOT NULL,
    file_size       INTEGER,
    content_hash    TEXT,               -- for duplicate detection / relink
    is_raw          INTEGER NOT NULL DEFAULT 0,
    capture_time    TEXT,               -- ISO8601, from EXIF
    import_time     TEXT NOT NULL,
    modified_time   TEXT,
    rating          INTEGER NOT NULL DEFAULT 0,   -- 0..5
    color_label     INTEGER NOT NULL DEFAULT 0,   -- 0=none,1..5
    pick_status     INTEGER NOT NULL DEFAULT 0,   -- -1 reject, 0 none, 1 pick
    orientation     INTEGER NOT NULL DEFAULT 1,
    width           INTEGER,
    height          INTEGER,
    is_virtual_copy INTEGER NOT NULL DEFAULT 0,
    master_photo_id INTEGER REFERENCES photos(id) ON DELETE CASCADE,
    online          INTEGER NOT NULL DEFAULT 1,    -- original reachable?
    has_smart_preview INTEGER NOT NULL DEFAULT 0,
    UNIQUE(folder_id, filename, is_virtual_copy, master_photo_id)
);
CREATE INDEX idx_photos_folder   ON photos(folder_id);
CREATE INDEX idx_photos_capture  ON photos(capture_time);
CREATE INDEX idx_photos_rating   ON photos(rating);
CREATE INDEX idx_photos_label    ON photos(color_label);
CREATE INDEX idx_photos_hash     ON photos(content_hash);

-- Searchable camera/EXIF metadata, 1:1 with photos (split out to keep photos lean).
CREATE TABLE metadata (
    photo_id     INTEGER PRIMARY KEY REFERENCES photos(id) ON DELETE CASCADE,
    camera_make  TEXT, camera_model TEXT, lens TEXT,
    iso INTEGER, aperture REAL, shutter REAL, focal_length REAL,
    exposure_bias REAL,                 -- EV; drives HDR bracket detection
    gps_lat REAL, gps_lon REAL,
    caption TEXT, copyright TEXT, creator TEXT,
    raw_json TEXT                       -- full metadata blob for the long tail
);
CREATE INDEX idx_metadata_camera ON metadata(camera_model);
CREATE INDEX idx_metadata_iso    ON metadata(iso);
```

### Develop edits (non-destructive)

Edits are versions of a photo's processing graph, stored as JSON (the same node
parameter schema the processing engine consumes). JSON keeps the schema stable as
the adjustment set grows — new nodes don't require migrations.

```sql
CREATE TABLE develop_versions (
    id           INTEGER PRIMARY KEY,
    photo_id     INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    name         TEXT,                  -- snapshot name; NULL = current
    is_current   INTEGER NOT NULL DEFAULT 1,
    graph_json   TEXT NOT NULL,         -- serialised processing graph + params
    process_version TEXT NOT NULL,      -- pipeline/compat version
    created_time TEXT NOT NULL,
    updated_time TEXT NOT NULL
);
CREATE INDEX idx_develop_photo ON develop_versions(photo_id, is_current);

-- Append-only audit of adjustments, powering History.
CREATE TABLE edit_history (
    id        INTEGER PRIMARY KEY,
    photo_id  INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    ts        TEXT NOT NULL,
    action    TEXT NOT NULL,            -- e.g. "Exposure", "Paste Settings"
    delta_json TEXT
);
CREATE INDEX idx_history_photo ON edit_history(photo_id, ts);
```

### Keywords, collections, smart collections

```sql
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
    parent_id INTEGER REFERENCES collections(id) ON DELETE CASCADE,  -- collection sets
    name      TEXT NOT NULL,
    kind      TEXT NOT NULL DEFAULT 'standard'  -- 'standard' | 'smart'
);
CREATE TABLE collection_photos (
    collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    photo_id      INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    sort_order    INTEGER,
    PRIMARY KEY (collection_id, photo_id)
);
-- Smart collections store a rule tree (JSON); evaluated to a live query.
CREATE TABLE smart_collections (
    collection_id INTEGER PRIMARY KEY REFERENCES collections(id) ON DELETE CASCADE,
    rules_json    TEXT NOT NULL,        -- {match:'all', rules:[{field,op,value}…]}
    match_type    TEXT NOT NULL DEFAULT 'all'
);
```

### Presets, exports, HDR groups

```sql
CREATE TABLE presets (
    id        INTEGER PRIMARY KEY,
    uuid      TEXT UNIQUE NOT NULL,
    folder    TEXT,                     -- preset folder/pack
    name      TEXT NOT NULL,
    graph_json TEXT NOT NULL,           -- node params (Vibe Photo canonical)
    source    TEXT,                     -- 'native' | 'professional raw editors-xmp'
    is_favorite INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE preset_usage (
    id        INTEGER PRIMARY KEY,
    photo_id  INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    preset_id INTEGER REFERENCES presets(id) ON DELETE SET NULL,
    ts        TEXT NOT NULL
);

CREATE TABLE exports (
    id         INTEGER PRIMARY KEY,
    photo_id   INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    preset     TEXT, dest_path TEXT, fmt TEXT,
    width INTEGER, height INTEGER, ts TEXT NOT NULL, status TEXT
);

CREATE TABLE hdr_groups (
    id          INTEGER PRIMARY KEY,
    result_photo_id INTEGER REFERENCES photos(id) ON DELETE SET NULL,
    created_time TEXT NOT NULL,
    params_json TEXT
);
CREATE TABLE hdr_group_members (
    group_id INTEGER NOT NULL REFERENCES hdr_groups(id) ON DELETE CASCADE,
    photo_id INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    ev REAL,
    PRIMARY KEY (group_id, photo_id)
);
```

### Full-text search

```sql
CREATE VIRTUAL TABLE photo_fts USING fts5(
    filename, keywords, caption, camera,
    content='',                          -- external-content / contentless
    tokenize='unicode61'
);
-- Kept in sync by triggers / the indexer on insert/update.
```

## 3. Design rationale

- **JSON for develop graphs & smart-collection rules:** the adjustment set and
  rule vocabulary evolve fast; storing them as JSON avoids a migration per new
  node and keeps the relational core (searchable fields) stable and indexed.
- **`metadata` split from `photos`:** the hot browsing query touches `photos`
  (small, indexed) without dragging the wide metadata blob into every page.
- **Volumes + relative paths:** originals can move drives/mounts; relinking
  updates a volume row, not 100k photo rows.
- **Virtual copies via self-reference:** a virtual copy is a `photos` row with a
  `master_photo_id` and its own `develop_versions` — no separate table.
- **Append-only `edit_history`:** powers professional History and audit without
  mutating the current state.

## 4. Integrity, migration, maintenance

- All writes in transactions through the single catalog writer.
- Migrations: numbered, forward-only scripts gated by `schema_meta.schema_version`,
  run inside a transaction with an automatic pre-migration backup.
- Maintenance ops (see [`05-catalog-architecture.md`](05-catalog-architecture.md)):
  `VACUUM`/`ANALYZE` (optimize), `PRAGMA integrity_check` + rebuild (repair),
  timestamped file copy (backup).
