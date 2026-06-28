# 10 — UI Wireframes

Dark, dockable, modern (professional RAW editors-familiar with a Figma-like fluidity). Modules
swap the central surface; panels dock around it. Implemented shell: see
`vibephoto/ui/main_window.py`.

## 1. Library module (Grid)

```
┌───────────────────────────────────────────────────────────────────────────┐
│  File  View  Window  Help                          [ Library ] [ Develop ] │  menu + module switch
├───────────┬───────────────────────────────────────────────┬───────────────┤
│ CATALOG   │  ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐     │ METADATA      │
│ ▸ Folders │  │IMG │ │IMG │ │IMG │ │IMG │ │IMG │ │IMG │     │ Camera  …     │
│ ▸ Collect.│  └────┘ └────┘ └────┘ └────┘ └────┘ └────┘     │ Lens    …     │
│ ▸ Smart   │  ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐     │ ISO     …     │
│           │  │IMG │ │IMG │ │IMG │ │IMG │ │IMG │ │IMG │     │ ──────────    │
│ KEYWORDS  │  └────┘ └────┘ └────┘ └────┘ └────┘ └────┘     │ KEYWORDS      │
│           │           (virtualised thumbnail grid)         │ [+ add]       │
├───────────┴───────────────────────────────────────────────┴───────────────┤
│ FILMSTRIP  ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ │
├───────────────────────────────────────────────────────────────────────────┤
│ Library              1,248 photos · 312 selected         Vibe Photo 0.1.0 │  status bar
└───────────────────────────────────────────────────────────────────────────┘
```
Toolbar (above grid): rating/flag/label filters, sort, search box, thumbnail-size
slider, grid/loupe/compare/survey toggles.

## 2. Develop module

```
┌───────────────────────────────────────────────────────────────────────────┐
│  File  View  Window  Help                          [ Library ] [ Develop ] │
├───────────┬───────────────────────────────────────────────┬───────────────┤
│ NAVIGATOR │                                                │ ▸ Light       │
│ ┌───────┐ │                                                │   Exposure ──○│
│ │ thumb │ │                                                │   Contrast ─○─│
│ └───────┘ │              ┌───────────────────┐             │   Highlights  │
│           │              │                   │             │   Shadows     │
│ PRESETS   │              │   image canvas    │             │ ▸ Color       │
│ ▸ Favs    │              │  (zoom/pan/loupe) │             │ ▸ Curve       │
│ ▸ RealEst.│              │                   │             │ ▸ HSL / Color │
│ ▸ B&W     │              └───────────────────┘             │ ▸ Detail      │
│           │            before │ after   ⤺ history          │ ▸ Lens        │
├───────────┴───────────────────────────────────────────────┴───────────────┤
│ FILMSTRIP  ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ ▭ │
└───────────────────────────────────────────────────────────────────────────┘
```
Right panel = the adjustment stack from [`06`](06-processing-engine.md); each group
collapses. Sliders are double-click-to-reset; values editable numerically.

## 3. Import dialog

```
┌ Import ───────────────────────────────────────────────────────────────────┐
│ Source                 │  ▭ ▭ ▭ ▭ ▭ (preview grid, checkboxes)  │ File Handling│
│  ▸ SD Card / Volume    │  ▭ ▭ ▭ ▭ ▭                              │ ○ Add       │
│  ▸ Folder…             │  ▭ ▭ ▭ ▭ ▭                              │ ○ Copy      │
│                        │                                        │ ○ Move      │
│ [✓] Eject after import │  [ Select All ]  [ New Photos Only ]    │ Apply Preset│
│                        │                                        │ Keywords… │
│                        │                          [ Import 248 ] │ Destination│
└───────────────────────────────────────────────────────────────────────────┘
```

## 4. Export dialog

```
┌ Export ───────────────────────────────────────────────────────────────────┐
│ Preset                 │ Format   [ JPG ▾ ]   Quality [▭▭▭▭▭○] 85          │
│  ▸ Web                 │ Color    [ sRGB ▾ ]                               │
│  ▸ Instagram           │ Resize   [✓] Long edge [ 2048 ] px                │
│  ▸ MLS                 │ Sharpen  [ Screen ▾ ]                             │
│  ▸ Real Estate         │ Metadata [ All ▾ ]   [✓] Watermark [ studio.png ]│
│  ▸ Print               │ Output   ~/Exports/{shoot}/{filename}            │
│  ▸ Full Resolution     │                                                  │
│ [ + New Preset ]       │                         [ Export 312 photos ]    │
└───────────────────────────────────────────────────────────────────────────┘
```

## 5. HDR / Real-Estate merge dialog (right-click → Create HDR)

```
┌ Create HDR ───────────────────────────────────────────────────────────────┐
│ Detected group: 7 frames (−3…+3 EV)        Preview ┌───────────────┐       │
│ Alignment   [ Auto ▾ ]                              │   merged      │       │
│ Deghost     [▭▭▭○──] Medium                         │   preview     │       │
│ Apply preset[ Warm Real Estate ▾ ]                  └───────────────┘       │
│ Output      [✓] DNG  [✓] TIFF  [✓] JPG                                      │
│ [ Real-Estate Auto Process ▾ ]                      [ Cancel ] [ Merge ]    │
└───────────────────────────────────────────────────────────────────────────┘
```

## 6. Keyboard shortcuts (industry-standard)

| Key | Action | Key | Action |
|-----|--------|-----|--------|
| `G` | Grid (Library) | `D` | Develop |
| `E` | Loupe | `C` | Compare |
| `F` | Fullscreen | `R` | Crop |
| `0–5` | Set rating | `6–9` | Color labels |
| `P` / `X` | Pick / Reject | `Ctrl+C/V` | Copy / Paste settings |
| `Ctrl+Shift+C/V` | Copy/Paste develop | `\` | Before/After toggle |
| `Ctrl+Shift+I` | Import | `Ctrl+Shift+E` | Export |
| `Ctrl+Z / Ctrl+Y` | Undo / Redo | `Ctrl+S` | Save metadata to XMP |

Phase 1 wires module/fullscreen/quit/about and the switcher; the rest land with
their modules.

## 7. Interaction & layout principles
- **Dockable & customisable:** every panel is a `QDockWidget` (movable, tabbable,
  closable); layout persists per user via `QSettings`. "Reset Workspace" restores
  defaults.
- **Non-blocking:** long actions show progress in the status bar / a jobs popover;
  the UI never freezes.
- **Smoothness:** virtualised grid, GPU-friendly canvas, debounced slider→render,
  preview-first then 1:1 refinement (see [`11`](11-performance-strategy.md)).
- **Theme:** neutral dark palette tuned for colour-critical work (`resources/themes/dark.qss`).
