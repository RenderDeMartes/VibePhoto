"""Headless batch operations over many photos (no UI dependency).

:func:`auto_edit_photo` computes a one-click Auto-Edit for a single photo and saves
it, reusing the exact same logic as the Develop module: develop the base at
identity, analyse that, and store the resulting :class:`EditState` as the photo's
edit. It is resolution-independent (Auto-Tone reads relative statistics), so a fast
preview-size load gives the same result as the full image — which keeps a batch over
hundreds of photos tractable.
"""

from __future__ import annotations

from pathlib import Path

from vibephoto.processing.auto import auto_hdr, auto_tone
from vibephoto.processing.edit_state import EditState
from vibephoto.processing.layers import LayerStack
from vibephoto.processing.loader import ImageLoader
from vibephoto.processing.pipeline import PipelineRenderer
from vibephoto.processing.store import DevelopStore

#: Preview long-edge used for batch analysis — small enough to be quick, large
#: enough for stable tone statistics.
BATCH_ANALYSIS_EDGE = 1024

#: Batch auto kinds → the analysis function they apply.
AUTO_KINDS = {"edit": auto_tone, "hdr": auto_hdr}


def apply_preset_to_photo(
    store: DevelopStore,
    photo_id: int,
    name: str,
    state: EditState,
    *,
    new_layer: bool,
) -> None:
    """Apply a preset's ``state`` to a photo's stored edit.

    ``new_layer`` stacks it on a new layer over the existing edits; otherwise it
    replaces the edit with a single base layer carrying the preset.
    """
    if new_layer:
        stack = store.load(photo_id)
        stack.add_layer(name or "Preset")
        stack.active_layer.state = state.copy()
    else:
        stack = LayerStack.single(state)
    store.save(photo_id, stack)


def auto_edit_photo(
    loader: ImageLoader,
    store: DevelopStore,
    path: Path,
    photo_id: int,
    *,
    is_raw: bool,
    kind: str = "edit",
    long_edge: int = BATCH_ANALYSIS_EDGE,
) -> bool:
    """Auto-edit one photo and persist it. Returns ``True`` on success.

    Develops the base at identity (so a RAW is tone-mapped, not raw-linear), analyses
    that image with the chosen auto ``kind`` (``"edit"`` = auto-tone, ``"hdr"`` =
    single-image HDR look), and saves the result for ``photo_id``.
    """
    base = loader.load(path, is_raw=is_raw, long_edge=long_edge)
    if base is None:
        return False
    developed = PipelineRenderer(base).render(EditState())  # identity develop = "Before"
    auto_fn = AUTO_KINDS.get(kind, auto_tone)
    store.save(photo_id, LayerStack.single(auto_fn(developed)))
    return True
