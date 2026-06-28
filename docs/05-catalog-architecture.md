# 05 — Catalog Architecture

## 1. What a catalog is

A **catalog** is a single `.vibephoto` SQLite database (schema in
[`04`](04-database-schema.md)) plus a sidecar cache directory for previews and
smart previews. It is the source of truth for organisation and edits; originals
live on disk and are referenced, not copied (unless the user imports-by-copy).

The catalog layer (`vibephoto.catalog`) exposes repositories and services
behind interfaces resolved from the DI container:

- `CatalogService` — open/create/close/backup/optimize/repair; owns the writer.
- `PhotoRepository`, `FolderRepository`, `CollectionRepository`, `KeywordRepository`.
- `IndexerService` — incremental filesystem indexing.
- `SidecarService` — XMP read/write synchronisation.
- `SearchService` — filters + FTS query building.

## 2. Concurrency: single writer, many readers

WAL mode gives many concurrent readers and exactly one writer. We therefore route
**all writes through one serialised connection** (a writer queue on a dedicated
thread), while UI/read queries use short-lived read connections from a pool. This
eliminates `database is locked` races and keeps the GUI responsive while imports
and edits commit in the background.

**Tradeoff:** write throughput is bounded by one writer — fine for an interactive
DAM (writes are small and bursty), and far simpler/safer than multi-writer
schemes.

## 3. Multiple catalogs

A user may keep several catalogs (per-client, per-year). Only one is "active" at a
time in the UI; the Application layer manages open/switch with a clean shutdown of
the previous catalog's services. Catalog-independent settings live in the global
config; catalog-specific state lives in the `.vibephoto` file.

## 4. Sidecar support & portability

Three modes (`metadata.sidecar_mode`):

| Mode | Behaviour | Use case |
|------|-----------|----------|
| **catalog** | Edits/metadata only in the catalog | Fastest; single machine |
| **sidecar** | Edits/metadata mirrored to `.xmp` next to RAWs | Interop with professional RAW editors/Bridge; move files between systems |
| **hybrid** (default) | Catalog is primary; XMP written for portability | Best of both — fast locally, portable when needed |

`SidecarService` writes adjustments and metadata into XMP (via ExifTool / direct
XMP for sidecars) and reads them on import, so **users can move images between
systems without losing edits**. Sidecar writing is debounced and configurable.

## 5. Incremental indexing

Importing or "synchronising" a folder must scale to 10k+ files without freezing:

1. **Enumerate** the folder tree on an I/O thread; diff against the catalog
   (new / changed by mtime+size / missing).
2. **Insert** new `photos` rows in batched transactions; mark missing as offline.
3. **Read embedded metadata** (fast EXIF) to populate searchable fields + FTS.
4. **Queue** thumbnail + standard-preview generation on the compute/I/O pools.
5. **Emit progress events** throughout; the grid fills in as previews land.

Re-indexing is incremental (hash/mtime diff), so re-syncing a large folder is cheap.

## 6. Smart previews & offline editing

A **smart preview** is a compressed, reduced-resolution proxy (lossy, ~2560 px
long edge, stored under the cache dir). When an original is offline (drive
unplugged), the develop pipeline transparently sources the smart preview, so the
photographer keeps editing; edits reapply to the full original on relink. The
`online` flag and `has_smart_preview` column drive this fallback. See
[`11`](11-performance-strategy.md) for cache budgets.

## 7. Relinking

Originals move. Relinking matches by `content_hash` (and filename/size heuristics)
and updates the `volumes`/`folders` rows, reconnecting many photos at once. Manual
"locate folder" is offered when automatic matching is ambiguous.

## 8. Smart collections engine

A smart collection stores a **rule tree** (`{match: all|any, rules: [...]}`) as
JSON. `SearchService` compiles it to a parameterised SQL query (joining
`photos`/`metadata`/`photo_keywords`/`photo_fts`) evaluated live, so membership
updates automatically as photos change. Rules cover ratings, labels, flags,
camera/lens/ISO, dates, keywords, folder, filename text, and edit status.

## 9. Virtual folders & virtual copies

- **Virtual copies:** alternate edits of one master (a `photos` row with
  `master_photo_id`), each with its own develop version.
- **Virtual folders / collections:** organisational groupings independent of disk
  layout (the `collections` tree), including collection sets (nesting).

## 10. Backup, optimize, repair

- **Backup:** on launch (configurable) and on demand — a checkpointed copy of the
  `.vibephoto` file with a timestamp; retention via `catalog.max_backups`.
- **Optimize:** `ANALYZE` + `VACUUM` to reclaim space and refresh query plans.
- **Repair:** `PRAGMA integrity_check`; on corruption, recover into a fresh DB and
  restore from the latest good backup; never silently lose edit data.

## 11. Performance posture (100k+ photos)

- Browsing queries hit only the narrow, indexed `photos` table; metadata and
  develop blobs are loaded lazily per selection.
- Grid uses windowed/virtualised loading (only visible thumbnails are realised).
- FTS5 + targeted indexes keep search/filter under the 200 ms target.
- All writes are async and batched; the UI thread never touches SQLite directly.
