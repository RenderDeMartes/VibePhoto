# 12 — Milestone Roadmap

Built in phases; each phase: architecture → design choices → production code →
tests → verify before advancing.

## Status

| Phase | Title | Status |
|-------|-------|--------|
| **1** | **Foundation** | ✅ **Complete** |
| **2** | **Catalog DB, thumbnails, metadata indexing** | ✅ **Complete (incl. live Library grid)** |
| 3 | RAW loading & preview generation | 🔄 In progress |
| 4 | Develop module & processing engine | 🔄 In progress (+ undo/redo, preset combo) |
| 5 | Preset system (incl. XMP import) | 🔄 Import + library + combo browser |
| 6 | HDR engine | Planned |
| 7 | Batch processing | Planned |
| 8 | Export engine | 🔄 Core (JPG/PNG/TIFF + presets) |
| 9 | Plugin SDK | Planned |
| 10 | Optimization, packaging, release | 🔄 Win bundle building |

## Phase 1 — Foundation ✅
**Delivered:** project scaffold + packaging; DI container; layered/validated
settings; structured logging; typed event bus; service lifecycle host; cross-
platform paths; error hierarchy; headless `Application` + composition root; CLI
entry; PySide6 dark-theme main-window shell (module switch, dockable panels, menus,
shortcuts, workspace persistence).
**Verification:** 54 tests pass (50 headless + 4 GUI offscreen); ruff clean; app
launches headless (`--headless`) and GUI; screenshot confirms layout.
**Exit criteria:** ✅ headless core runs with no Qt; ✅ green suite; ✅ window launches.

## Phase 2 — Catalog, thumbnails, indexing ✅
**Delivered:** SQLite catalog (schema [`04`](04-database-schema.md)) with WAL +
single-writer `Database`, `PRAGMA user_version` migrations; domain models; folder/
photo/metadata/collection repositories with FTS5 search; `CatalogService`
(lifecycle, open/create/close/backup/optimize/repair); Pillow metadata reader;
incremental `IndexerService` (scan/diff/insert/metadata, progress events); disk +
LRU `ThumbnailCache`; catalog events; bootstrap wiring. **Live Library grid:** a
`QAbstractListModel`/`QListView` thumbnail grid bound to the catalog, a Qt event
bridge (bus→GUI-thread signals), and a background **Import Folder** action.
**Verification:** 93 tests pass; mypy strict 0 issues across all 45 files; ruff
clean; screenshot confirms a populated thumbnail grid after import.
**Exit criteria:** ✅ index a folder in the background; ✅ photos + metadata +
thumbnails appear in the grid; ✅ incremental re-sync skips unchanged files.
**Deferred refinements:** read-connection pool (currently one serialised conn),
on-disk thumbnail eviction, filmstrip binding, smart-collection query compilation.

## Phase 3 — RAW loading & previews 🔄
**Delivered:** pluggable decoder registry (`RawDecoder` Protocol + `DecoderRegistry`)
with a rawpy/LibRaw decoder; embedded-JPEG preview fast path with a half-size
render fallback when a file has no embedded thumbnail; full LibRaw decode
(`RawImage`); RAW camera metadata (master dimensions + EXIF read from the embedded
preview; orientation from the preview EXIF, else mapped from LibRaw's flip). A
`RawService` façade is wired into the thumbnail cache (RAW grid previews) and the
indexer (RAW metadata). rawpy stays an optional extra: when it is absent the
headless core still runs and the grid falls back to placeholders. The DI container
was hardened to fall back to a parameter's default for optional `X | None`
constructor dependencies.
**Verification:** 114 tests pass — orchestration via fakes (no native dep) plus a
real-LibRaw integration suite against a committed synthetic DNG fixture (and an
env-gated `VIBEPHOTO_TEST_RAW` hook for real camera files); mypy strict 0 issues (47
files); ruff clean. A real DNG decodes end-to-end through
`RawService → ThumbnailCache → catalog` and renders as a real thumbnail in the
Library grid.
**Remaining (Phase 3 tail):** smart previews (cached downsized renders for offline
editing); ICC / camera-profile assignment (color management — lands with the
Phase 4 pipeline); optional OpenImageIO decode path.
**Risks:** per-camera RAW quirks; OpenImageIO availability (optional path).

## Phase 4 — Develop module & processing engine 🔄
**Delivered:** a headless, non-destructive processing engine — `ImageBuffer`,
pure NumPy adjustment operators, and an ordered `Stage` pipeline (White Balance →
Exposure → Tone → Presence → Color → Curves → HSL/B&W → Color Grade → Detail →
Effects) driven by a serialisable `EditState`. A `PipelineRenderer` **memoizes
each stage and recomputes only downstream of a changed parameter** (a single-
slider re-render measured ~1 ms on a preview buffer). Full Develop control set:
WB, exposure, contrast, HSWB tone, texture/clarity/dehaze, vibrance/saturation,
parametric + point tone curves, 8-band HSL, B&W mixer, 3-way colour grading,
sharpening, noise reduction, vignette, grain. `DevelopEngine` opens a photo into a
renderer; edits persist per-photo via a JSON `DevelopStore`. *(Update: RAW now opens
through the real LibRaw demosaic — see the Phase 4 follow-ups — not the embedded
JPEG.)* **UI:** a Develop module with a fit-to-window canvas, a
before/after toggle (`\`), a spec-driven adjustments panel (Basic/HSL/Detail/
Effects + B&W), Reset, and **Load Preset…**; Library double-click / `D` opens the
selected photo. The DI container, headless-core invariant, and colour pipeline are
all honoured (engine imports no Qt).
**Verification:** 153 tests pass (operators, memoization correctness, edit-state
serialisation, store roundtrip, loader/engine, XMP import, Develop GUI smoke);
mypy strict 0 issues (59 files); ruff clean. A real third-party `.xmp` preset
renders a correct faded-film look end-to-end on a photographic image (before/after
verified), and the Develop UI renders with the preset applied.
**Simplifications (documented):** display-referred working space for JPEGs (RAW now
develops scene-linear — see the follow-ups); no full ICC colour management yet;
linear stage chain (no tiling / branching DAG yet); synchronous preview-resolution
render (worker-thread + 1:1 refinement later). *(Update: tone-curve and colour-grade
now have interactive editors; a live low-res **smart preview** proxy backs slider
drags; and RAW develops in **scene-linear** — all in the Phase 4 follow-ups.)*
**Exit (met for the core):** slider→preview well under 150 ms via memoization;
the same `EditState` graph drives the live preview and (in a later phase) export.
**Risks:** rendering correctness vs. performance — guarded by the perf benchmarks.

## Phase 5 — Presets 🔄
**Landed:** import for **both common preset formats** — `.xmp`
(`xmp_import`) and legacy `.lrtemplate` Lua presets (`lrtemplate_import`) — sharing
one `crs:`→`EditState` mapping (`mapping.py`); a `PresetLibrary` that imports preset
folders and groups them by pack; and a Develop **two-combo browser** (folder ▸
preset) with **live hover preview**. Verified against a large third-party preset
set plus legacy `.lrtemplate` samples.
**Still to build:** favourites/marketplace, in-app preset folder management, XMP
export ([`08`](08-preset-system.md)).
**Exit:** download a professional RAW editors preset (either format) → apply immediately ✅;
documented compat gaps.

## Phase 4 follow-ups (landed)
**Undo/redo** (`EditHistory`, Ctrl+Z / Ctrl+Y / Ctrl+Shift+Z) with coalesced
slider steps; the **preset combo + hover preview**; and the **Library navigator**
wired to real catalog folders (click to filter the grid) — the old placeholder is
gone.

**Edit layers** — a photo's edit is now a `LayerStack` of adjustment layers
composed bottom-to-top (`LayerRenderer` with per-layer memoization). The sliders
edit the active layer, so you can Auto-Edit one layer and drop a preset on
another; layers can be toggled, added, deleted, and reordered-by-stack. The panel
lists them **newest-on-top** (professional layer editors convention) while the stack still composes
bottom-to-top. Persists as JSON and reads older single-`EditState` saves
transparently.

**Develop tools footer + edit modes** — a compact action bar under the canvas
(`DevelopFooter`): a 5-star rating control, **composition overlays** (rule of
thirds, golden-ratio phi grid, golden spiral/triangles, diagonals, grid, center
cross, quarter-thirds — `overlays.py`, normalized polyline geometry) with
opacity / 90° rotation / H+V flip, **zoom −/+** with a live label, and **Copy /
Paste / Edit-like-last** (the last replays the most-recently-committed stack via
`LastEdit`). The canvas gained **zoom & pan** — scroll-wheel zoom toward the
cursor, left-drag to pan, double-click toggles Fit↔100%. The adjustments panel now
has **Simple / Intermediate / Advanced** modes that progressively reveal sliders
and whole sections (each `SliderSpec`/group carries a `level`), defaulting to
Intermediate.

**Smart previews + interactive graphs** — editing now renders a fast low-res
**proxy** (<=1024 px) live while sliders/curves/wheels move, then swaps in the crisp
full-size preview ~180 ms after the edits settle (two debounce timers + a second
`LayerRenderer` over a downscaled base; small images skip the proxy). Two
professional graph widgets landed in the panel: a draggable **tone-curve
editor** (`curve_editor.py` — master RGB + per-channel R/G/B point curves, WYSIWYG
straight-line interpolation matching the `point_curves` op) and **colour-grading
wheels** (`color_wheels.py` — Shadows/Midtones/Highlights/Global hue-sat wheels with
luminance, balance, and blending, driving the `grade_*` fields). Both wire through
the panel's existing change plumbing (`curve_changed` / `param_changed`).

**Editing the real RAW (not the JPEG preview)** — the Develop module previously
edited the camera's embedded JPEG (8-bit, baked WB/tone), so it behaved like editing
a flattened image. It now decodes the **actual RAW through LibRaw** to a 16-bit
demosaic (`from_uint16`), giving edits real tonal range; the live preview uses a
fast *half-size* demosaic and export/1:1 the full decode, so **the preview matches
the export**. The embedded JPEG is only a fallback when the real decode is
unavailable.

**Scene-linear RAW develop (the professional RAW editors workflow)** — RAW now decodes to
**scene-linear** light (`gamma=(1,1)`, `no_auto_bright`, camera WB; tagged
`colorspace="linear"`) and the pipeline runs a linear front-end before the display
tail: white balance, exposure (a true `2**EV` stop), and Highlights/Shadows/Whites/
Blacks all in linear (`scene_linear.py`), then a base **tone-map** with a gentle
highlight shoulder converts to display sRGB (`PipelineRenderer` picks the front-end
by the base's colorspace). This gives **real highlight headroom and recovery** —
detail above 8-bit clipping survives and pulls back, which editing the flattened
JPEG could never do (verified: recovered highlight detail vs. 0.0 on the 8-bit
path). Previews/proxies downscale in float (`resample.downscale_buffer`) to keep the
linear data; "Before" shows the identity *develop* (tone-mapped), not the raw linear
pixels; export uses the same chain so it matches the preview.

**Kelvin white balance + eyedropper** — RAW now has a true pro WB workflow: a
**Temperature (Kelvin) + Tint** panel (`white_balance_panel.py`) shown only for RAW
(the relative Temp/Tint sliders hide), driving `wb_kelvin`/`wb_tint` through a
blackbody model applied in linear (`scene_linear.white_balance_kelvin`; higher K =
warmer). A **White Balance Selector** eyedropper samples a canvas pixel and solves
Temp/Tint to neutralise it (`solve_white_balance`); **As Shot** resets to the 6500 K
reference and **Auto** grey-worlds the frame.

**Highlight reconstruction + clipping warnings** — a RAW-only **Highlight Recovery**
slider (`scene_linear.reconstruct_highlights`, field `highlight_recovery`, a stage in
the linear front-end) rolls colour-clipped highlights toward neutral white, so a blown
sky/bulb resolves cleanly instead of keeping a cyan/magenta cast. The histogram gained
professional **clipping indicators**: corner triangles that light up (white when all
channels clip, tinted to the clipped channel otherwise) for shadows (top-left) and
highlights (top-right).

**True per-camera Kelvin** — the WB Temperature slider now reads the *real* as-shot
colour temperature. `raw/colortemp.py` recovers the scene illuminant from the camera's
as-shot WB multipliers + `rgb_xyz_matrix` (XYZ→cam) and applies McCamy's CCT formula;
`RawService.as_shot_temperature` surfaces it, and the WB panel calibrates its slider so
"as shot" displays e.g. **5339 K** (validated on real Canon CR2s) while the engine's
`wb_kelvin` stays 6500-anchored (so identity/serialisation/tests are untouched).
*(Validated against a 200-shot CR2 set: our scene-linear render matches LibRaw's
reference, and the end-to-end RAW test passes on real files via `VIBEPHOTO_TEST_RAW`.)*
*(Still ahead: a wider-gamut working space + ICC output profiles — colour management.)*

**Auto Edit / Auto HDR** — image-adaptive one-click tone (`processing.auto`):
Auto centres exposure + recovers clipping; Auto HDR adds a single-image HDR
tone-map (multi-bracket HDR merge remains Phase 6). **Copy/Paste Settings** —
a settings clipboard with panel buttons, a Library right-click menu, and
Shift-click to paste onto every selected photo. Sliders ignore the scroll wheel
(scroll the panel without nudging values).

## Library follow-ups (landed)
**Star ratings** — press **0-5** to rate the selected photos (persisted to the
catalog, shown as a star badge on each thumbnail) and a **rating filter** (≥ N)
that narrows the grid; the **filmstrip mirrors the filtered set**, so in Develop
you step through only your picks. Still to come: flags (P/X), colour labels,
keyword/metadata search, and collections UI.

## Phase 6 — HDR engine
**Build:** bracket detection, alignment, deghosting, radiance merge, tone-map
handoff, outputs; **Real-Estate Auto Process** profile/pipeline.
**Exit:** right-click Create HDR; 10-room real-estate set → MLS + full-res < 3 min.

## Phase 7 — Batch processing
**Build:** copy/paste/sync settings, batch preset apply, batch metadata, async job
manager with progress/cancel across hundreds–thousands of images.
**Exit:** sync 1,000 photos without UI stalls; failures isolated per item.

## Phase 8 — Export engine 🔄
**Landed (core):** `ExportService` renders a photo's edits at **full resolution**
through the same pipeline (a full LibRaw decode for RAW), then resizes/watermarks
and writes **JPG/PNG/TIFF**; built-in **export presets** (Full-Res / Web /
Instagram / MLS / TIFF / PNG); **batch export** with progress, wired to
File → Export (Ctrl+Shift+E) and run off the GUI thread.
**Still to build:** DNG/HDR writers; explicit colour-space conversion + ICC;
metadata/EXIF policy; output sharpening; user-defined export presets.
**Exit:** batch export with watermark + resize ✅; output matches develop preview.

## Phase 9 — Plugin SDK
**Build:** discovery/loading, manifest, capability host API, dependency isolation,
process sandbox, versioning; published reference + templates + example plugins; AI
extension seams.
**Exit:** install a third-party export + processing plugin; sandboxed; SDK docs ship.

## Phase 10 — Optimization, packaging, release 🔄
**Landed early:** a **PyInstaller Windows bundle** (`packaging/Vibe Photo.spec`,
`scripts/build_exe.py` → `dist/Vibe Photo/Vibe Photo.exe`) that bundles the package data,
the rawpy/LibRaw native binaries, and excludes unused Qt subsystems. Per project
convention (`CLAUDE.md`), the executable is rebuilt at the end of each request.
**Still to build:** profiling pass against all perf targets; macOS/Linux bundles
(Briefcase); a true installer (Inno Setup/NSIS); code signing; auto-update + crash
reporting.
**Exit:** signed installers on three platforms; all [`11`](11-performance-strategy.md)
targets met.

## Cross-cutting (every phase)
Type hints, tests (unit + integration), SOLID/DI, comprehensive logging, headless-
core invariant, perf-regression budget. AI modules (scene/subject/sky/culling/
dedupe/tagging) arrive as plugins post-v1 on the Phase 9 seams — **no core refactor
required**.

## Risk register (top)
| Risk | Impact | Mitigation |
|------|--------|------------|
| RAW format quirks | Wrong colors/decode fails | Pluggable decoders; per-camera tests; embedded-preview fallback |
| Perf at 100k | Sluggish UI | Virtualisation, caching, benchmarks as gates |
| GPU portability | Uneven acceleration | CPU baseline guaranteed; per-node fallback |
| XMP fidelity | Looks differ from professional RAW editors | Faithful param mapping + documented gaps |
| Native deps (OIIO/ExifTool) | Install friction | Optional extras; bundled in Phase 10 packaging |
