# 08 — Preset System Design

A preset is a reusable set of develop parameters. The critical requirement:
**import industry-standard XMP presets and apply them immediately**, so photographers
can use looks they buy or download online.

## 1. Preset model

A native preset is portable JSON — the same node-parameter schema the processing
engine consumes (`graph_json`), plus metadata:

```json
{
  "uuid": "…", "name": "Warm Real Estate", "folder": "Real Estate",
  "source": "native", "process_version": "1",
  "graph": { "nodes": [ {"type": "exposure", "params": {"ev": 0.15}},
                        {"type": "whitebalance", "params": {"temp": 5600, "tint": 6}},
                        {"type": "curves", "params": {"rgb": [[0,0],[128,140],[255,255]]}} ] }
}
```

Storing presets in the **engine's own schema** means applying a preset is just
merging its nodes/params into the photo's graph — no translation at apply time.

## 2. Library organisation
- **Folders / packs:** presets live in named folders; a pack is a distributable
  bundle (folder + manifest + optional thumbnails).
- **Favourites:** `is_favorite` for quick access.
- **Usage tracking:** `preset_usage` records applications (for "recently used" and
  future recommendation).
- **Marketplace hooks:** packs carry a manifest (author, version, license, preview
  images) so an in-app marketplace/installer can list and install them; install =
  import pack into the `presets` table + copy any LUTs/profiles into the cache.

## 3. XMP preset import — the conversion layer

This is the heart of compatibility. These presets are XMP files carrying `crs:`
(camera-raw-settings) attributes. The converter maps them onto Vibe Photo nodes.

### 3.1 Pipeline
```
.xmp / .lrtemplate → parse → crs:* dict → ParameterMapper → node graph → native preset
```
- **Parse:** read XMP (ExifTool or direct XML); `.lrtemplate` (Lua-ish) is parsed
  for legacy presets.
- **Map:** a declarative table maps each `crs` key to a node + param + transform.
- **Emit:** build the native `graph_json`; store with `source="professional raw editors-xmp"`.

### 3.2 Mapping table (excerpt)

| professional RAW editors `crs:` key | Vibe Photo node.param | Transform |
|----------------------|-------------------------|-----------|
| `Exposure2012` | exposure.ev | identity (EV) |
| `Contrast2012` | contrast.amount | scale −100..100 → node range |
| `Highlights2012` / `Shadows2012` | tone.highlights / tone.shadows | identity |
| `Whites2012` / `Blacks2012` | tone.whites / tone.blacks | identity |
| `Temperature` / `Tint` | whitebalance.temp / .tint | Kelvin / identity |
| `Vibrance` / `Saturation` | color.vibrance / .saturation | identity |
| `Texture` / `Clarity2012` / `Dehaze` | presence.texture / .clarity / .dehaze | identity |
| `ToneCurvePV2012*` | curves.rgb / r/g/b | point-list parse |
| `HueAdjustment*` / `SaturationAdjustment*` / `LuminanceAdjustment*` | hsl.{band}.{h,s,l} | per-band |
| `ColorGrade*` (shadow/mid/highlight hue/sat/lum) | colorgrade.* | HSL→node |
| `Sharpness` / `SharpenRadius` / `SharpenDetail` / `SharpenEdgeMasking` | sharpen.amount/radius/detail/masking | identity |
| `LuminanceSmoothing` / `ColorNoiseReduction` | noise.luminance / .color | identity |
| `LensProfileEnable` / distortion / vignette / CA | lens.* | flags + amounts |

### 3.3 Fidelity & gaps
- **Versioning:** `process_version` lets us interpret 2012-process values
  correctly and evolve our own ranges without breaking imported presets.
- **Unsupported keys** (e.g. point-color, AI masks) are recorded in a
  `compat_warnings` list on the preset and surfaced to the user, rather than
  failing the import. The preset still applies everything it *can*.
- A **round-trip export** to XMP lets users send looks back to professional RAW editors-based
  collaborators; mapping is bidirectional where a key exists on both sides.

## 4. Applying presets
- Single photo: merge preset nodes into the current develop graph (preserving or
  replacing existing values per the apply mode: "all settings" vs "additive").
- **Batch:** apply one preset to a selection asynchronously (see
  [`02`](02-technical-architecture.md) threading); each photo gets a new/updated
  `develop_versions` row.

## 5. Tradeoffs
- **Canonical = engine schema:** zero translation at apply/render time; the cost is
  that XMP import/export carries the mapping complexity — the right place for it.
- **Lossy by necessity:** the original editor's proprietary rendering won't match pixel-perfect;
  we map parameters faithfully and document gaps, which is what "use them
  immediately" realistically requires.
