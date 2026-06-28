# 11 — Performance Strategy

Performance is a first-class design constraint, considered in every layer.

## 1. Targets (restated, measurable)

| Scenario | Target |
|----------|--------|
| Catalog size | 100,000+ photos, responsive |
| Import + index | 10,000 photos efficiently in the background |
| Grid scroll / zoom / pan | smooth (≈60 fps), no stalls |
| Search / filter (100k) | < 200 ms |
| Develop slider → preview | < 150 ms at fit-to-screen |
| Crash-free sessions | > 99.5% |

## 2. Concurrency

- **GUI thread does no heavy work** — Qt event loop only.
- **Native libraries release the GIL** (NumPy, OpenCV, LibRaw, OpenImageIO,
  Pillow), so image work genuinely parallelises across an OS-thread compute pool
  sized to cores. The GIL is not the bottleneck for the hot path.
- **Two pools:** I/O-bound (indexing, disk previews, metadata) and CPU-bound
  (decode, develop, HDR, export), independently sized.
- **Cancellation + priority:** newer preview requests cancel stale ones; user-
  visible work outranks background prefetch.
- Pure-Python hotspots, if any, can move to a process pool; native threading is the
  primary lever.

## 3. Caching tiers

| Tier | Content | Store | Budget |
|------|---------|-------|--------|
| **Thumbnails** | small grid images | disk (cache dir) + RAM LRU | `cache.max_thumbnail_cache_mb` (default 2 GB) |
| **Standard previews** | screen-res JPEG | disk + RAM LRU | `cache.max_preview_cache_mb` (default 8 GB) |
| **Smart previews** | compressed editable proxy (~2560 px) | disk | grows with library; user-managed |
| **Pipeline intermediates** | node output buffers | RAM (per session) | bounded; LRU by `cache_key` |

LRU eviction enforces byte budgets. Embedded-JPEG extraction from RAW gives
instant first thumbnails before full decode completes.

## 4. Responsive browsing at scale
- **Virtualised grid/filmstrip:** only visible cells are realised; thumbnails load
  async with placeholders and fade in.
- **Windowed queries:** browsing hits the narrow indexed `photos` table; wide
  metadata/develop blobs load lazily on selection.
- **Incremental indexing:** diff by mtime+size+hash; re-sync is cheap.
- **FTS5 + targeted indexes:** meet the search target without full scans.

## 5. Fast, fluid develop
- **Resolution-independent graph:** render preview-resolution first, refine to 1:1
  in the background (see [`06`](06-processing-engine.md)).
- **Memoize + invalidate downstream only:** a slider drag re-runs a few cheap nodes
  on cached upstream buffers.
- **Tiled rendering:** parallel tiles, bounded memory for big RAWs.
- **Debounce** slider input; coalesce rapid changes into one render.

## 6. GPU offload
The processing `Backend` abstraction lets demosaic/tone/sharpen/NR/merge ops move
to OpenCL/CUDA/Metal with per-node CPU fallback and device-resident buffer caching
— **no change to nodes, graph, or UI**. CPU remains the guaranteed baseline.

## 7. Memory discipline
- 32-bit float working buffers are large; tiling + buffer reference-counting + LRU
  caps keep peak memory bounded.
- Catalog uses WAL + page cache tuning; read connections are short-lived.
- Smart previews bound editing memory when originals are large/offline.

## 8. Measurement & guardrails
- **Benchmarks** for: import/index throughput, search latency, slider→preview
  latency, export throughput, HDR merge time — run on representative datasets.
- **Profiling** hooks (timing logs via structured logging; optional `cProfile`/
  `py-spy`) behind a debug flag.
- **Regression budget:** key benchmarks tracked across phases; a regression beyond
  threshold blocks merge. Targets in §1 are the acceptance gates.

## 9. Why this meets the goals
Headless, native-threaded compute + multi-tier caching + virtualised UI + a
memoizing, resolution-independent pipeline + an optional GPU path together deliver
"professional feel" at 100k+ photos and large RAWs, with CPU-only as the floor.
