# 03 — Folder Structure

## 1. Layout

A **src-layout** package keeps imports honest (you test the installed package,
not the working directory) and matches modern Python packaging.

```
Vibe Photo/
├── pyproject.toml              # packaging, deps, extras, tooling config
├── README.md
├── .gitignore
├── docs/                       # the 12 architecture documents
├── src/
│   └── vibephoto/
│       ├── __init__.py         # version + app constants
│       ├── __main__.py         # CLI entry point (python -m vibephoto)
│       ├── py.typed            # PEP 561 typing marker
│       │
│       ├── core/               # (0) foundation — DI, config, logging, events…
│       │   ├── container.py
│       │   ├── config.py
│       │   ├── logging.py
│       │   ├── events.py
│       │   ├── lifecycle.py
│       │   ├── paths.py
│       │   └── errors.py
│       │
│       ├── app/                # (2) application layer / composition root
│       │   ├── application.py
│       │   └── bootstrap.py
│       ├── services/           # (2) use-cases & view-models
│       │
│       ├── catalog/            # (3) SQLite catalog / DAM
│       ├── metadata/           # (4) EXIF/IPTC/XMP + ExifTool
│       ├── raw/                # (5) RAW decode & preview extraction
│       ├── processing/         # (6) node-based processing engine
│       ├── hdr/                # (7) HDR / real-estate pipeline
│       ├── presets/            # (8) presets + XMP conversion
│       ├── export/             # (9) render-to-file
│       ├── plugins/            # (10) plugin host + SDK
│       ├── cache/              # thumbnail / preview / smart-preview cache
│       │
│       ├── ui/                 # (1) PySide6 desktop UI (only Qt importer)
│       │   ├── main_window.py
│       │   ├── module_views.py
│       │   ├── theme.py
│       │   └── run.py
│       ├── resources/          # bundled assets (themes, icons, profiles)
│       │   └── themes/dark.qss
│       └── utils/              # pure cross-cutting helpers
│
└── tests/                      # pytest suite (headless core + gui-marked)
```

## 2. Mapping to the brief's folder list

The brief listed `/app /catalog /raw /processing /hdr /presets /export /plugins
/metadata /cache /ui /resources /settings /services /utils`. All are present as
packages under `src/vibephoto/`. Two deliberate adjustments, with rationale:

| Brief folder | Decision | Why |
|--------------|----------|-----|
| `/settings` | Folded into `core/config.py` (logic) + the per-user config dir (data) | A separate code package for settings would duplicate `core/config`; user settings *data* lives in the OS config dir, not in source. The brief's intent (typed settings + persistence) is fully met. |
| *(new)* `core/` | Added | The brief had no home for DI/logging/event/error infrastructure. A dedicated foundation package is standard and keeps these out of `services` (business logic) and `utils` (pure helpers). |

These are the only deviations; they improve cohesion without losing any
responsibility from the brief.

## 3. Where things live (responsibility index)

- **Wiring/lifecycle:** `app/bootstrap.py`, `app/application.py`, `core/lifecycle.py`
- **Settings:** `core/config.py` (model + loader), data in `AppPaths.settings_file`
- **Logging:** `core/logging.py`
- **DI:** `core/container.py`
- **Eventing:** `core/events.py`
- **Catalog DB:** `catalog/` (schema in `docs/04`)
- **RAW pipeline entry:** `raw/`; pixel pipeline: `processing/`
- **Automation:** `hdr/` (HDR + Real-Estate Auto Process)
- **Preset import/convert:** `presets/`
- **Output:** `export/`
- **Extensibility:** `plugins/`
- **UI:** `ui/` only

## 4. Conventions

- One responsibility per module; no monolithic files; no global mutable state
  (singletons come from the DI container, not module globals).
- Every package has a docstring stating its responsibility, dependencies, and the
  phase it's built in.
- Public, typed surface marked with `py.typed`; `from __future__ import annotations`
  in every module.
- Tests mirror the package they cover (`tests/test_<area>.py`); GUI tests carry
  the `gui` marker and skip cleanly without PySide6.
