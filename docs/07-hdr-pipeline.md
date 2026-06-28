# 07 — HDR Pipeline Design

HDR is a flagship feature; the **Real-Estate Auto Process** is the headline
automation. Both live in `vibephoto.hdr`, run headless, and hand off to the
processing engine for tone mapping and preset application.

## 1. HDR merge pipeline

```
Bracket detection → Alignment → Deghosting → Merge (radiance) → Tone-map handoff
                 → Preview → (optional preset) → Output (HDR/DNG/TIFF/JPG)
```

### 1.1 Bracket detection
Group candidate frames automatically using EXIF:
- same camera/lens, contiguous `capture_time` within a small window,
- monotonic `exposure_bias` (EV) sequence (e.g. −3…+3),
- matching resolution/orientation.

Detection yields `hdr_groups` proposals (see [`04`](04-database-schema.md)); the
user can accept, adjust membership, or trigger manually via **right-click → Create
HDR**.

### 1.2 Alignment
Hand-held brackets need registration. Default: feature/ECC-based alignment
(OpenCV `findTransformECC` / Median-Threshold-Bitmap for speed), estimating a
translation+rotation (optionally homography) per frame against the reference
(usually the EV0 frame). Tripod shots short-circuit when alignment is near-identity.

### 1.3 Deghosting
Moving subjects (trees, cars, people) cause ghosts. Strategy:
- compute per-pixel motion/consistency masks across the aligned stack,
- in motion regions, select from a single reference exposure rather than blending,
- blend static regions normally. Strength is configurable (none → aggressive).

### 1.4 Merge to radiance
Combine aligned, deghosted frames into a high-dynamic-range, scene-linear
radiance image (camera-response-weighted; Debevec/Robertson-style, or direct
linear-RAW weighting when RAW data is available — preferred, since RAW is already
near-linear and high-bit). Output is 32-bit float in the working space.

### 1.5 Tone-map handoff
The radiance image enters the **processing engine** as the source buffer of a
normal develop graph. "Tone mapping" is therefore just the standard tone/exposure/
highlights/shadows/clarity nodes — no separate, divergent renderer. This keeps one
pipeline, one preview, one export path.

### 1.6 Output
- **HDR/DNG:** a floating-point/linear DNG preserving dynamic range for re-editing.
- **TIFF (16-bit):** archival, tone-mapped.
- **JPG:** delivery, tone-mapped + sharpened for output.

Each merge records its `hdr_groups` row and `params_json` for reproducibility.

## 2. Real-Estate Auto Process

A single right-click action chains the full production workflow; **every step is
configurable** (and individually toggleable) via a profile:

| # | Step | Engine |
|---|------|--------|
| 1 | Detect bracketed images | `hdr` bracket detection |
| 2 | Create HDR merge | `hdr` merge |
| 3 | Apply selected preset | `presets` → `processing` |
| 4 | Vertical correction | `processing` Transform node |
| 5 | Lens correction | `processing` Lens node (profile-based) |
| 6 | Noise reduction | `processing` NR node |
| 7 | Sharpening | `processing` Sharpen node |
| 8 | Optional window pull | masked exposure/highlight recovery (local adjustment) |
| 9 | Export MLS JPG | `export` (MLS preset: sized, sRGB, watermark optional) |
| 10 | Export full-resolution JPG | `export` (Full Resolution preset) |

The action operates per detected group, so selecting a whole shoot processes every
room's bracket set hands-off. Target: a 10-room, 7-bracket shoot → MLS + full-res
exports in **< 3 minutes**.

### Configurability
A **Real-Estate profile** (stored like a preset) captures: bracket tolerances,
alignment/deghost strength, the develop preset, correction toggles, window-pull
parameters, and the two export presets. Studios save profiles per client/MLS.

## 3. Concurrency & performance
- Detection and merges run on the compute pool; multiple groups process in
  parallel up to a memory budget (radiance buffers are large).
- Alignment/merge use OpenCV (GIL-releasing, SIMD); a GPU merge op can slot in via
  the processing backend abstraction.
- Progress and failures surface as events; one bad group never aborts the batch.

## 4. Failure handling
- Mis-detected brackets are surfaced for confirmation rather than silently merged.
- If alignment fails (too much motion), the user is offered single-frame fallback
  or manual reference selection — no corrupt output is written.
