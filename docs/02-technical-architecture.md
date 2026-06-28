# 02 — Technical Architecture

## 1. Architectural style

Vibe Photo is a **layered, dependency-injected, event-decoupled** desktop
application with a **headless processing core**. The defining invariant:

> **The processing engine, HDR engine, catalog, and every domain/compute layer
> never import the UI layer.** Dependencies point *downward* only.

This makes the whole engine runnable without Qt — in CI, on batch/render nodes,
from a future CLI/server, and in unit tests — and is the foundation of the
project's testability and performance story.

## 2. Layers

```
┌──────────────────────────────────────────────────────────────────┐
│ 1. UI Layer (PySide6)            vibephoto.ui                   │  imports ↓ only
├──────────────────────────────────────────────────────────────────┤
│ 2. Application Layer             vibephoto.app, .services       │  composition root,
│                                                                    │  use-cases, view-models
├──────────────────────────────────────────────────────────────────┤
│ 3. Catalog   4. Metadata   8. Preset   9. Export   10. Plugin      │  domain layers
│    .catalog     .metadata     .presets    .export     .plugins     │
├──────────────────────────────────────────────────────────────────┤
│ 5. RAW   6. Processing Engine   7. HDR Engine   • Cache            │  compute layers
│    .raw     .processing            .hdr            .cache          │
├──────────────────────────────────────────────────────────────────┤
│ 0. Core (foundation)             vibephoto.core, .utils         │  DI, config, logging,
│                                                                    │  events, lifecycle, paths
└──────────────────────────────────────────────────────────────────┘
```

**Allowed dependency directions** (enforced by review + import-linting in later phases):

- `ui` → `app` → domain → compute → `core`.
- Any layer → `core`/`utils`.
- **Never** the reverse. Cross-domain calls go through the Application layer or
  the event bus, not by importing a sibling's internals.

## 3. Cross-cutting foundation (`core`)

Implemented in Phase 1:

| Component | File | Responsibility |
|-----------|------|----------------|
| **DI container** | `core/container.py` | Interface→impl binding, singleton/transient/scoped lifetimes, constructor injection by type hint, cycle detection |
| **Config** | `core/config.py` | Typed, layered settings (defaults → JSON file → env), validated |
| **Logging** | `core/logging.py` | Console + rotating file handlers, JSON option, namespaced |
| **Event bus** | `core/events.py` | Typed pub/sub, MRO routing, handler isolation |
| **Lifecycle** | `core/lifecycle.py` | `Service` protocol + `ServiceHost` ordered start/rollback |
| **Paths** | `core/paths.py` | Cross-platform config/data/cache/log dirs |
| **Errors** | `core/errors.py` | Single rooted exception hierarchy |

### Composition root
`app/bootstrap.py` is the **only** place the object graph is assembled. It loads
config, configures logging, builds the container, registers singletons, and wires
services into the `ServiceHost`. Everything else depends on abstractions resolved
from the container. This centralises wiring (auditable in one file) and lets tests
swap any implementation.

## 4. Threading & concurrency model

Python's GIL is released by the heavy native libraries we use (NumPy, OpenCV,
LibRaw, OpenImageIO, Pillow's C paths), so **CPU-bound image work parallelises
across OS threads** despite the GIL. The model:

- **GUI thread:** Qt event loop only. Never does I/O or pixel crunching.
- **I/O thread pool:** indexing, metadata reads, thumbnail disk I/O.
- **Compute thread pool:** demosaic, develop, HDR, export — sized to CPU cores.
- **Single catalog writer:** SQLite in WAL mode allows many readers + one writer;
  catalog writes are serialised through one connection/queue.
- **Cross-thread delivery:** workers publish results to the `EventBus`; a thin Qt
  adapter (UI layer) marshals those onto the GUI thread via signals.

Cancellation and progress are first-class: long jobs accept a cancellation token
and report progress through events. (Process pools are an option for pure-Python
hotspots, but native-lib threading is the primary lever.)

**Tradeoff:** Threads share memory (cheap hand-off of large image buffers) at the
cost of careful synchronisation. We accept this because zero-copy buffer sharing
matters more for an image app than process isolation; the catalog's single-writer
rule contains the main shared-mutable-state risk.

## 5. Error handling

- All intentional failures derive from `Vibe PhotoError` with a `code` and
  `context`. Layers subclass it (`CatalogError`, `RawDecodeError`, …).
- Background jobs convert exceptions into failure events; they never crash the
  GUI thread.
- A global `sys.excepthook` (UI layer) logs unhandled GUI-thread exceptions and
  shows a recoverable dialog rather than vanishing.

## 6. Technology choices & tradeoffs

| Choice | Why | Tradeoff / mitigation |
|--------|-----|------------------------|
| **Python 3.12** | Velocity, ecosystem (NumPy/OpenCV/rawpy), readability | Slower than C++; mitigated by native libs releasing the GIL and a GPU path |
| **PySide6 (Qt)** | Mature, native-feeling, dockable, cross-platform, official LGPL bindings | Large dependency; GUI isolated so the core never depends on it |
| **SQLite** | Zero-admin, single-file, fast, transactional, FTS5 search; perfect for a single-user catalog | Not multi-writer; we adopt WAL + single-writer; cloud/multi-user is a future redesign |
| **rawpy/LibRaw** | Broad RAW format support, embedded-preview extraction | Per-camera quirks; mitigated by a pluggable decoder registry |
| **OpenCV + NumPy** | Fast, vectorised, GIL-releasing image ops; HDR/align built-in | Large; only pulled in compute layers |
| **OpenImageIO** | Pro-grade format/colorspace/ICC handling, deep-bit TIFF/EXR | No universal wheel; documented as system dep, optional extra |
| **ExifTool** | The gold standard for metadata read/write across formats | External binary; path configurable; embedded EXIF used for the fast path |
| **Custom DI** | Tiny, explicit, dependency-free; keeps `core` clean | We own ~250 lines; justified by zero coupling and debuggability |

## 7. Scalability, performance, maintainability implications

- **Scalability:** Layer boundaries + DI let us scale teams (own a layer) and
  scale features (add a node/plugin) without touching unrelated code. The catalog
  is indexed and paged for 100k+; compute is data-parallel.
- **Performance:** Headless core means the hot path has no UI overhead; threading
  uses native libs; multi-tier caches (thumbnail/preview/smart-preview) and
  resolution-independent preview rendering keep interaction fluid. See
  [`11-performance-strategy.md`](11-performance-strategy.md).
- **Maintainability:** One composition root, type hints everywhere, single error
  hierarchy, event-decoupled producers/consumers, and a test suite that runs
  without a display. New backends (GPU) slot in behind existing interfaces.

## 8. Data flow (develop preview, illustrative)

```
UI slider → ViewModel (app) → DevelopSession sets node param
   → ProcessingGraph invalidates downstream nodes
   → Scheduler renders at preview resolution on compute pool
   → result buffer published as RenderReady event
   → Qt adapter marshals to GUI thread → canvas repaint
```

The same graph, asked for full resolution, drives export — guaranteeing
**what-you-see-is-what-you-export** parity.
