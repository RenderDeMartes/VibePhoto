"""Processing layer — the non-destructive, node-based image pipeline.

The heart of the editor. Edits are stored as parameters on nodes in a processing
graph (RAW Decode → Demosaic → White Balance → Exposure → Tone → Color → Lens →
Detail → Noise → Output). Each node has a CPU implementation behind an abstract
interface so GPU backends (OpenCL/CUDA/Metal) can replace it without changing
application logic. A scheduler resolves the graph at a requested resolution for
realtime preview and full-res export.

**This layer must never import the UI** and must be fully runnable headless.
Designed in: ``docs/06-processing-engine.md``.
Built in: Phase 4.
"""

from __future__ import annotations

from vibephoto.processing.auto import auto_hdr, auto_tone
from vibephoto.processing.clipboard import SettingsClipboard
from vibephoto.processing.edit_state import HSL_BANDS, EditState
from vibephoto.processing.engine import DevelopEngine
from vibephoto.processing.history import EditHistory
from vibephoto.processing.image_buffer import ImageBuffer
from vibephoto.processing.layered_renderer import LayerRenderer, render_stack
from vibephoto.processing.layers import EditLayer, LayerStack
from vibephoto.processing.loader import DEFAULT_PREVIEW_LONG_EDGE, ImageLoader
from vibephoto.processing.pipeline import PipelineRenderer, Stage, build_stages
from vibephoto.processing.store import DevelopStore

__all__ = [
    "DEFAULT_PREVIEW_LONG_EDGE",
    "HSL_BANDS",
    "DevelopEngine",
    "DevelopStore",
    "EditHistory",
    "EditLayer",
    "EditState",
    "ImageBuffer",
    "ImageLoader",
    "LayerRenderer",
    "LayerStack",
    "PipelineRenderer",
    "SettingsClipboard",
    "Stage",
    "auto_hdr",
    "auto_tone",
    "build_stages",
    "render_stack",
]
