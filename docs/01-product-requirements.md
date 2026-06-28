# 01 — Product Requirements Document (PRD)

**Product:** Vibe Photo
**Type:** Cross-platform desktop application (Windows, macOS, Linux)
**Category:** Professional RAW photo editor + digital asset manager (DAM)
**Positioning:** A faster, simpler, more automated photo catalog + editor,
with a flagship focus on RAW and HDR real-estate workflows.

---

## 1. Vision

A professional photographer should install Vibe Photo and be productive within
minutes. It must feel familiar to professional RAW editors users, but be faster on large
catalogs, simpler in its everyday workflows, and more automated for repetitive
production tasks (HDR brackets, real-estate batches, preset application).

We combine the strongest ideas from three products:

- **Legacy catalog editors** — catalog/DAM model, non-destructive develop, presets.
- **Capture One** — rendering quality, tethered/pro ergonomics, customisable UI.
- **Figma** — modern, fluid, dockable, collaborative-feeling interface.

…and add **workflow automation** (one-click HDR + Real-Estate Auto Process) as a
differentiator.

## 2. Target users & personas

| Persona | Needs | Why Vibe Photo |
|---------|-------|------------------|
| **Rachel — Real-estate photographer** | Shoots 8–12 properties/week, bracketed HDR, fast MLS turnaround | One-click "Real Estate Auto Process": bracket→HDR→preset→vertical/lens correction→export MLS + full-res |
| **Marco — Wedding/portrait pro** | 2,000–4,000 RAWs/event, fast culling, consistent looks | Fast import/cull, ratings/flags, batch presets, smart previews for offline editing |
| **Sofia — Landscape/fine-art** | Fewer images, maximum quality, precise control | High-quality RAW pipeline, curves/HSL/color-grading, careful color management |
| **Studio with assistants** | Shared catalogs, repeatable output | Catalog backup/repair, export presets, plugin-driven automation |

## 3. Goals and non-goals

### Goals (v1.0)
- Manage catalogs of **100,000+** photos with responsive browsing and search.
- Non-destructive RAW develop with a professional adjustment set.
- Import **industry-standard XMP presets** and apply them immediately.
- Flagship **HDR engine** and **Real-Estate Auto Process**.
- Batch everything (copy/paste/sync settings, batch presets, batch export).
- Robust export with format/colorspace/watermark/resize control and presets.
- Extensible via a documented **Plugin SDK**.

### Non-goals (v1.0)
- Cloud sync / multi-user concurrent editing of one catalog (designed-for, not shipped).
- Mobile apps.
- Full DAM features like face recognition at launch (AI is architected, not built).
- Tethered capture at launch (architecture leaves room; not a v1 commitment).

## 4. Functional requirements

### 4.1 Library / DAM
- Folder browsing of the filesystem; import into catalog (copy/move/add-in-place).
- Catalogs; collections; **smart collections** (rule-based, live).
- Keywords (hierarchical), metadata filters, full-text search.
- Ratings (0–5), color labels, flags (pick/reject), virtual copies, **virtual folders**.
- Fast thumbnails (background generation), cached previews, incremental indexing.
- Grid, Loupe, Compare, Survey views.

### 4.2 Develop
- Non-destructive; edits stored as adjustment metadata (a processing graph).
- Adjustment groups: **Light** (exposure, contrast, highlights, shadows, whites,
  blacks), **Color** (temp, tint, vibrance, saturation), **Presence** (texture,
  clarity, dehaze), **Curves** (RGB + per-channel), **HSL** (hue/sat/lum per band),
  **Color Grading** (shadows/midtones/highlights), **Detail** (sharpening:
  amount/radius/detail/masking; noise reduction: luminance/color), **Lens
  Corrections** (distortion, vignetting, CA), **Transform** (vertical/horizontal/
  perspective). Cropping, local masks (later phase).
- Before/after, history, snapshots, copy/paste/sync settings.

### 4.3 Presets
- Import/export XMP presets; preset folders, favourites, packs; marketplace hooks.
- Conversion layer maps RAW editors/professional RAW editors parameters to Vibe Photo nodes.

### 4.4 HDR
- Auto-detect bracket groups; right-click **Create HDR**: align, deghost, merge,
  preview, optional preset. Output HDR/DNG/TIFF/JPG.

### 4.5 Real-Estate Auto Process
- Right-click pipeline: detect brackets → HDR merge → preset → vertical correction
  → lens correction → noise reduction → sharpening → optional window pull → export
  MLS JPG + full-resolution JPG. Every step configurable.

### 4.6 Export
- JPG/PNG/TIFF/DNG/HDR; presets (Web, Instagram, MLS, Real Estate, Print, Full
  Resolution); watermark, resize, color space, metadata policy; batch export.

### 4.7 Plugins
- Import/export/preset-pack/HDR/processing/AI plugins; versioned, sandboxed,
  dependency-isolated, documented API.

## 5. Non-functional requirements

| Attribute | Requirement |
|-----------|-------------|
| **Scale** | 100,000+ photos/catalog; multiple catalogs; large RAW (50–100 MB) |
| **Import** | 10,000 photos imported & indexed efficiently in the background |
| **Responsiveness** | UI never blocks; all heavy work is async; 60 fps scroll/zoom/pan target |
| **Develop latency** | Sub-150 ms preview update for common slider edits at fit-to-screen |
| **Reliability** | Crash-safe catalog (WAL), auto-backup, repair; no edit data loss |
| **Portability** | Identical behaviour on Win/macOS/Linux; sidecar portability |
| **Color** | ICC/color-managed pipeline; camera profiles |
| **Quality** | Type hints everywhere, tests, SOLID, modular, comprehensive logging |
| **Security** | Sandboxed plugins; no silent network access; explicit telemetry opt-in |

## 6. Success metrics
- Time-to-first-productive-edit for a new professional RAW editors user: **< 10 minutes**.
- Real-estate set (7-bracket × 10 rooms) → exported MLS + full-res: **< 3 minutes** hands-off.
- Catalog of 100k photos: search/filter response **< 200 ms**; grid scroll **smooth**.
- Crash-free sessions **> 99.5%**.

## 7. Competitive positioning
- **vs legacy catalog editors:** faster large-catalog handling; built-in HDR + real-estate
  automation (no plugins/extra apps); modern dockable UI; preset compatibility.
- **vs Capture One:** simpler onboarding; automation-first; lower cost of entry;
  open plugin ecosystem.

## 8. Constraints & assumptions
- Python 3.12+, PySide6, SQLite, rawpy/LibRaw, OpenCV, NumPy, OpenImageIO, ExifTool, Pillow.
- ExifTool is an external binary; OpenImageIO may be a system dependency.
- GPU acceleration is designed-for but CPU is the guaranteed baseline.

## 9. Release scope
See [`12-roadmap.md`](12-roadmap.md). v1.0 = Phases 1–10. Phase 1 (foundation) is
implemented and tested in this repository.
