"""Render a :class:`LayerStack` by composing its layers bottom-to-top.

:func:`render_stack` is a one-shot render (used by export). :class:`LayerRenderer`
is the interactive variant: it keeps one memoizing :class:`PipelineRenderer` per
layer, each rooted on the layer below's output, so editing the active layer only
recomputes that layer (and the ones above it) while the layers beneath stay
cached — the same downstream-only-invalidation idea, one level up.
"""

from __future__ import annotations

from vibephoto.processing.edit_state import EditState
from vibephoto.processing.geometry import apply_geometry
from vibephoto.processing.image_buffer import ImageBuffer
from vibephoto.processing.layers import EditLayer, LayerStack
from vibephoto.processing.mask import blend_masked, combined_coverage
from vibephoto.processing.pipeline import PipelineRenderer


def _compose_layer(
    input_buffer: ImageBuffer, layer: EditLayer, developed: ImageBuffer, *, draft: bool
) -> ImageBuffer:
    """Blend a (already-developed) layer back over its input by its mask, if any.

    Without masks the developed buffer passes through (a global layer). With masks,
    the edit is composited only inside the combined coverage — against the layer's
    *identity* render of the same input, so the blend stays in display space.
    """
    coverage = combined_coverage(layer.masks, developed.height, developed.width)
    if coverage is None:
        return developed
    baseline = PipelineRenderer(input_buffer, draft=draft).render(EditState())
    blended = blend_masked(baseline.data, developed.data, coverage)
    return ImageBuffer(blended, developed.colorspace)


def render_stack(base: ImageBuffer, stack: LayerStack) -> ImageBuffer:
    """Apply photo-level geometry, then every enabled layer in order (no caching).

    Crop + straighten run once on the base; the layer stack develops the result.
    A layer with masks applies only inside its mask. With *no* enabled layer, a
    scene-linear (RAW) base is still developed at identity — the linear→display
    tone-map is the develop baseline, not an edit, so "all layers off" shows the
    neutral developed image (matching the Before view), never the dark raw-linear
    pixels. A display-referred (JPEG) base is already viewable, so it passes through.
    """
    base = apply_geometry(base, stack.geometry)
    current = base
    any_enabled = False
    for layer in stack.layers:
        if layer.enabled:
            any_enabled = True
            developed = PipelineRenderer(current).render(layer.state)
            current = _compose_layer(current, layer, developed, draft=False)
    if not any_enabled and base.colorspace == "linear":
        current = PipelineRenderer(base).render(EditState())
    return current


class LayerRenderer:
    """Composes a layer stack over a fixed base with per-layer memoization."""

    def __init__(self, base: ImageBuffer, *, draft: bool = False) -> None:
        self._base = base
        #: Draft = skip the blur-heavy stages for fast live previews (the low-res proxy).
        self._draft = draft
        self._renderers: list[PipelineRenderer] = []
        #: Identity develop of the base, for the "all layers off" case on a RAW.
        self._baseline: PipelineRenderer | None = None
        #: Cropped/straightened base + the geometry that produced it (cache key).
        self._geo_base = base
        self._geo_key: tuple[float, float, float, float, float] | None = None

    @property
    def base(self) -> ImageBuffer:
        return self._base

    def _geometry_base(self, stack: LayerStack) -> ImageBuffer:
        """The geometry-applied base, recomputing only when the crop/angle changed."""
        g = stack.geometry
        key = (g.left, g.top, g.right, g.bottom, g.angle)
        if key != self._geo_key:
            self._geo_key = key
            self._geo_base = apply_geometry(self._base, g)
            self._renderers.clear()  # the base changed shape — drop all caches
            self._baseline = None
        return self._geo_base

    def render(self, stack: LayerStack) -> ImageBuffer:
        geo_base = self._geometry_base(stack)
        current = geo_base
        any_enabled = False
        for index, layer in enumerate(stack.layers):
            # (Re)root this layer's renderer when its input buffer changed (a layer
            # below was edited/toggled) or when the stack grew.
            if index >= len(self._renderers) or self._renderers[index].base is not current:
                del self._renderers[index:]
                self._renderers.append(PipelineRenderer(current, draft=self._draft))
            if layer.enabled:
                any_enabled = True
                developed = self._renderers[index].render(layer.state)
                current = _compose_layer(current, layer, developed, draft=self._draft)
        del self._renderers[len(stack.layers) :]  # drop renderers for removed layers
        if not any_enabled and geo_base.colorspace == "linear":
            # No layer develops the linear base — apply the identity develop baseline
            # so the frame matches Before (developed), not the raw-linear pixels.
            if self._baseline is None:
                self._baseline = PipelineRenderer(geo_base, draft=self._draft)
            current = self._baseline.render(EditState())
        return current
