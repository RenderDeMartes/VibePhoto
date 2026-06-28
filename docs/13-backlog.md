# 13 — Backlog (nice-to-haves for a future session)

A running list of candidate work, grouped by theme. Each item notes **why**, a
**pointer** to where it touches, rough **effort**, and whether it's **validatable
without real camera files** (most are). Pick from the top of a group; nothing here
is blocking. Current state of the RAW workflow is in [`12-roadmap.md`](12-roadmap.md)
(Phase 4 follow-ups).

Validation note: the user has ~200 real Canon CR2s at `F:\Photos\TorontoRaw`. For
RAW/colour work, run the gated end-to-end test with
`VIBEPHOTO_TEST_RAW=F:/Photos/TorontoRaw/_MG_7826.CR2`.

---

## Local & geometric editing (highest-value, no colour risk)

- **Crop & straighten** — *Done 2026-06-28 (engine + presets UI):* photo-level
  `Geometry` (crop rect + straighten angle) on `LayerStack` (not per-layer EditState),
  applied to the base before the layer stack (`geometry.apply_geometry`,
  `layered_renderer`); serialised in the stack; Before view + all-layers-off both
  reflect the crop. UI = `ui/crop_panel.py` (centred aspect presets + straighten
  slider) **and an on-canvas crop tool**: a footer Crop toggle (`develop_footer`)
  shows the uncropped frame with a draggable crop rectangle (corners/edges/move,
  rule-of-thirds grid, dimmed surround — `ui/crop_overlay.py` + `DevelopCanvas`),
  90° rotate buttons (`Geometry.rotate90`), and a straighten slider. *Still ahead:*
  free-rotate handle + flip.
- **Local adjustments / masking** — *Engine done (tested):* `processing/mask.py`
  (`Mask` with `radial` / `linear` / `brush` coverage, add/subtract `combined_coverage`,
  `blend_masked`); `EditLayer.masks` is serialised; `layered_renderer._compose_layer`
  blends a masked layer's edited render over its identity render by coverage (correct in
  display space even for the RAW develop layer). *Panel UI done:* `ui/mask_panel.py`
  adds/tunes **radial** and **gradient (linear)** masks per active layer (position, size,
  feather, invert, subtract). *On-canvas editing done:* `ui/mask_overlay.py` (Qt-free
  hit-test / drag / paint geometry) + `DevelopCanvas` draws the mask overlay and edits it —
  drag a radial's centre/edges, drag gradient endpoints, paint **brush** strokes; an
  "Edit on canvas" toggle gates it. *Still ahead:* an **object/subject/sky select** mask
  kind (needs a segmentation model + dependency). *Effort: large (model).*
- **Spot removal / heal / clone** — sampled-source patching with feather/opacity.
  *Effort: medium-large. Validatable.*
- **Geometry / Upright** — perspective + keystone correction, auto-level.
  *Effort: medium. Validatable.*
- **Lens corrections** — *Manual controls done 2026-06-28:* `processing/lens.py`
  (radial distortion remap, chromatic-aberration re-converge, vignetting gain) as
  `EditState.lens_distortion` / `lens_ca` / `lens_vignetting` + pipeline stages
  (`lens_geometry` draft-skipped) and a "Lens Corrections" slider group. *Still ahead:*
  **profile-based automatic** correction — needs a lens-profile source (e.g. the open
  LensFun database, or LCP parsing). *Effort: large; needs profile data.*

## RAW & colour (parity tail)

- **Wide-gamut working space** — work in linear ProPhoto/Rec.2020, convert to sRGB
  at output. Colours already match LibRaw on sRGB, so this mainly helps wide-gamut
  displays + print export. Touches every operator's sRGB assumptions (Rec.709
  luminance in `tone_linear`/`luminance`/`vibrance`/`grade`) + a working→display
  conversion on every render. *Effort: large; validate with real files + a
  colorimeter ideally.* (ICC **output tagging** done — see below.)
  - *Done 2026-06-28:* exports embed the sRGB ICC profile
    (`export/color_profiles.py`, `export/writers.py`); files now declare their colour
    space instead of going out untagged. Wider output profiles (wide-gamut RGB/ProPhoto)
    wait on a real wide-gamut working space — without one they'd be cosmetic.
- **Creative/camera profiles** — *Done 2026-06-28:* `processing/profiles.py` (Neutral /
  Standard / Vivid / Portrait / Landscape / Flat / Matte / Warm Film / Cool Film /
  Monochrome) as a base-look stage at the head of the display tail (`EditState.profile`,
  pipeline `profile` stage), with a picker in `adjustments_panel`. *Still ahead:* true
  per-camera-matching profiles (would need measured camera data / DCP) and user-defined
  custom looks.
- **WB Tint in true units** — currently the Kelvin Temp is calibrated per-camera
  (`raw/colortemp.py`) but Tint stays a relative -100..100. Compute the as-shot Duv
  for a true green/magenta readout. *Effort: small-medium.*
- **RAW preset Kelvin mapping** — XMP/`lrtemplate` import maps `crs:Temperature`
  → `temp`; for RAW it should map to `wb_kelvin`. See `presets/mapping.py`.
  *Effort: small.*
- **DCP profile support.** *(Clipped-channel highlight handling done 2026-06-28:
  decode uses LibRaw `highlight_mode=Blend` so blown channels are rebuilt from
  unclipped ones instead of flattened to white, feeding real data to the in-pipeline
  `reconstruct_highlights` + Highlights/Recovery stages.)*

## Performance & rendering

- **Worker-thread rendering** — the preview render is synchronous on the GUI
  thread (`develop_module._render_full/_render_preview`). Move to a worker with a
  1:1 refinement pass. `docs/11` perf targets. *Effort: medium.*
- **1:1 zoom refinement** — at >Fit zoom the canvas upscales the proxy/preview;
  decode a full-res crop for the visible region. *Effort: medium.*
- **GPU seam** — the `ops`/`Stage` design already isolates pixel math; a GPU
  backend (e.g. via a compute path) could replace hot stages. *Effort: large.*
- **Tiled / branching DAG renderer** — needed for local masks; lands with that
  feature.

## Library & catalog

- **Flags (P/X), colour labels, keyword/metadata search, Collections UI** — noted
  as "still to come" in the Library follow-ups. *Effort: medium each. Validatable.*
- **Smart collections** — compile saved queries to SQL.
- **Read-connection pool** — catalog currently serialises through one connection.
- **On-disk thumbnail eviction** — cap the thumbnail cache size.

## Export, presets, batch, HDR

- **Export**: DNG/HDR writers, explicit colour-space *conversion* (wide-gamut RGB/ProPhoto —
  waits on a wide-gamut working space), metadata/EXIF policy, output sharpening,
  user-defined export presets (`export/` — Phase 8 tail).
  - *Done 2026-06-28:* sRGB **ICC embedding** on every export
    (`export/color_profiles.py`); **16-bit TIFF** export via `tifffile`
    (`writers._write_tiff16`, `ImageBuffer.to_uint16`, `ExportPreset.bit_depth` +
    dialog selector) so the 16-bit develop pipeline no longer collapses to 8-bit at
    output. Resize moved pre-quantise (float) for both depths. JPEG/PNG stay 8-bit
    (no 16-bit RGB writer).
- **Presets**: favourites, in-app preset-folder management, XMP **export**.
- **Batch (Phase 7)**: sync settings across a selection, batch preset apply, an
  async job manager with progress/cancel.
- **HDR (Phase 6)**: bracket detection, alignment, deghosting, radiance merge, and
  the Real-Estate Auto Process profile.

## UX polish

- **Clip-overlay toggle on the canvas (professional RAW editors "J")** — paint blown highlights /
  crushed shadows on the image; pairs with the histogram clip indicators already in
  `ui/histogram.py`. *Effort: small. Validatable.*
- **Interactive parametric curve** — drag the curve graph's highlight/light/dark/
  shadow regions directly (today they're separate sliders feeding `parametric_curve`).
- **Before/After side-by-side** view modes (currently a toggle only).
- **Snapshots / virtual copies / history panel UI** — surface `EditHistory` and add
  named snapshots.

## Testing / infra

- **Performance regression budget** as CI gates (`docs/11`).
- Consider a tiny committed real-RAW fixture (or keep the `VIBEPHOTO_TEST_RAW`
  env-gated path against `F:\Photos\TorontoRaw`).
