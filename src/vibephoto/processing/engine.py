"""DevelopEngine — opens a photo for editing and renders its edits.

The headless entry point to the processing layer: ``open()`` loads a photo into a
:class:`PipelineRenderer` (which owns the per-stage memoization cache for that
image), and the caller then renders any number of :class:`EditState`s against it
cheaply. The same engine powers the live Develop preview, batch apply, and export
— it imports no UI.
"""

from __future__ import annotations

import logging
from pathlib import Path

from vibephoto.processing.layered_renderer import LayerRenderer
from vibephoto.processing.loader import DEFAULT_PREVIEW_LONG_EDGE, ImageLoader
from vibephoto.processing.pipeline import PipelineRenderer

logger = logging.getLogger(__name__)


class DevelopEngine:
    """Creates renderers for photos and exposes one-shot rendering."""

    def __init__(self, loader: ImageLoader) -> None:
        self._loader = loader

    def open(
        self, path: Path, *, is_raw: bool, long_edge: int = DEFAULT_PREVIEW_LONG_EDGE
    ) -> PipelineRenderer | None:
        """Load ``path`` into a single-edit memoizing renderer, or ``None``."""
        base = self._loader.load(path, is_raw=is_raw, long_edge=long_edge)
        if base is None:
            logger.warning("Develop could not open %s", path)
            return None
        return PipelineRenderer(base)

    def open_layered(
        self, path: Path, *, is_raw: bool, long_edge: int = DEFAULT_PREVIEW_LONG_EDGE
    ) -> LayerRenderer | None:
        """Load ``path`` into a layer-stack renderer for the Develop module."""
        base = self._loader.load(path, is_raw=is_raw, long_edge=long_edge)
        if base is None:
            logger.warning("Develop could not open %s", path)
            return None
        return LayerRenderer(base)

    @property
    def loader(self) -> ImageLoader:
        return self._loader
