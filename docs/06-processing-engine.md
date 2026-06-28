# 06 — Processing Engine Architecture

## 1. Principles

- **Non-destructive:** edits are parameters, never pixels on the original.
- **Node-based graph:** every adjustment is a node; the photo's edit state is a
  directed acyclic graph of nodes + parameters (serialised as `graph_json`).
- **Resolution-independent:** the same graph renders a fast preview or a full-res
  export — guaranteeing WYSIWYG parity.
- **Backend-abstracted:** each node has a CPU implementation behind an interface;
  GPU backends (OpenCL/CUDA/Metal) can replace it **without changing app logic**.
- **UI-independent:** `vibephoto.processing` imports no Qt and runs headless.

## 2. The canonical pipeline

```
RAW Decode → Demosaic → White Balance → Exposure/Tone → Color → Lens Corrections
          → Detail (Sharpen) → Noise Reduction → Output (color convert / encode)
```

Each stage maps to one or more nodes. Linear, scene-referred working space
(linear RGB in a wide gamut, 32-bit float) is used internally; the Output stage
converts to the target display/export profile.

## 3. Node model

```python
class Node(Protocol):
    id: str
    type: str                      # "exposure", "curves", "sharpen", …
    params: Mapping[str, Any]      # validated against the node's ParamSchema
    inputs: Sequence[str]          # upstream node ids

    def process(self, ctx: RenderContext, inputs: list[ImageBuffer]) -> ImageBuffer: ...
    def param_schema(self) -> ParamSchema: ...
    def cache_key(self, upstream_key: str) -> str:  # for memoization
        ...
```

- `ImageBuffer` wraps a NumPy/where-available GPU array + color-space + ROI/tile
  metadata. Buffers are reference-counted and shared zero-copy between threads.
- `RenderContext` carries target resolution, ROI/tile, working profile, the
  device/backend, a cancellation token, and the cache.
- Nodes are **pure**: output depends only on inputs + params, which makes
  memoization and parallelism safe.

### Node catalog (Develop set)
Light (exposure, contrast, highlights, shadows, whites, blacks) · Color (temp,
tint, vibrance, saturation) · Presence (texture, clarity, dehaze) · Curves (RGB +
R/G/B) · HSL (8 bands × hue/sat/lum) · Color Grading (shadows/mid/highlights +
blend/balance) · Detail/Sharpen (amount, radius, detail, masking) · Noise
Reduction (luminance, color) · Lens (distortion, vignette, CA) · Transform
(vertical, horizontal, perspective, rotate, crop). Local masks (radial/linear/
brush/AI) attach as parameterised sub-graphs in a later phase.

## 4. Graph & scheduler

- **GraphCompiler** validates the node DAG (no cycles; param schemas satisfied)
  and produces a topologically-ordered execution plan.
- **Scheduler** executes the plan on the compute thread pool. It:
  - **memoizes** intermediate buffers by `cache_key` so moving the Sharpen slider
    doesn't re-decode the RAW or re-run White Balance;
  - **invalidates** only nodes downstream of a changed parameter;
  - renders **tiled** for large images (parallel tiles, bounded memory);
  - honours **cancellation** (a newer preview request supersedes an in-flight one);
  - renders at **preview resolution** first, then optionally refines to 1:1.

This delivers the sub-150 ms preview target: most slider drags only re-execute a
few cheap downstream nodes on a cached upstream buffer at fit-to-screen size.

## 5. Backend abstraction (CPU / GPU)

```python
class Backend(Protocol):
    name: str                      # "cpu", "opencl", "cuda", "metal"
    def is_available(self) -> bool: ...
    def make_op(self, node_type: str) -> NodeOp: ...   # backend-specific kernel
```

- The DI container binds a `Backend` chosen from `processing.gpu_backend`
  (`auto` probes availability; `cpu` forces the baseline).
- A node asks the active backend for its `NodeOp`; if a GPU op is missing, the
  scheduler **falls back to CPU per-node**, so partial GPU coverage still works.
- `ImageBuffer` abstracts device memory; the scheduler inserts host⇄device
  transfers only at backend boundaries and caches device-resident buffers.

**Tradeoff:** the abstraction adds indirection vs. hard-coding NumPy, but it is
what lets GPU acceleration land later **without touching node logic, the graph, or
the UI** — the single most important scalability decision for image throughput.

## 6. Color management

- Decode to scene-linear; assign the camera/input profile (camera profile or DCP).
- All math in linear, wide-gamut float.
- Output node applies rendering intent + converts to sRGB/wide-gamut RGB/Display-P3/
  ProPhoto/custom ICC for preview and export. OpenImageIO/`littlecms` handle ICC.
- Soft-proofing hooks live in the Output stage (later phase).

## 7. Headless execution & reuse

Because the engine is UI-free, the **exact same graph + scheduler** powers:
- live develop previews (preview resolution, cancellable),
- batch/sync edits (apply one graph to N photos),
- export (full resolution),
- HDR tone mapping (post-merge handoff from `vibephoto.hdr`),
- tests (render a known graph, assert on output buffers).

## 8. Performance & maintainability implications

- **Performance:** memoization + downstream-only invalidation + tiling + preview-
  first rendering keep editing fluid; GPU path scales to large RAWs and batches.
- **Scalability:** new adjustments = new node classes + param schema; no engine
  rewrite. JSON graph keeps persistence stable.
- **Maintainability:** pure nodes are unit-testable in isolation; the scheduler is
  the single place concurrency/caching live; backends are swappable and testable
  against the CPU reference for correctness.
