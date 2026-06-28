"""ExportService — render a photo's edits at full resolution and write it out.

The same resolution-independent pipeline that drives the live preview renders the
final image here, just at full resolution: load the master (a full LibRaw decode
for RAW), apply the stored :class:`EditState`, resize/watermark per the
:class:`ExportPreset`, and write the file. Batch export iterates with a progress
callback so the UI can run it off the GUI thread.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from vibephoto.export.presets import ExportPreset
from vibephoto.export.writers import apply_watermark, write_image
from vibephoto.processing.layered_renderer import render_stack
from vibephoto.processing.layers import LayerStack
from vibephoto.processing.loader import ImageLoader
from vibephoto.processing.resample import downscale_buffer
from vibephoto.processing.store import DevelopStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExportItem:
    """One photo to export: where it is, whether it is RAW, and its catalog id."""

    path: Path
    is_raw: bool
    photo_id: int | None = None


@dataclass
class ExportResult:
    exported: int = 0
    failed: int = 0
    outputs: list[Path] = field(default_factory=list)


ProgressFn = Callable[[int, int], None]


class ExportService:
    """Renders edited photos to disk via export presets."""

    def __init__(self, loader: ImageLoader, store: DevelopStore) -> None:
        self._loader = loader
        self._store = store

    def export_photo(
        self, item: ExportItem, preset: ExportPreset, dest_dir: Path
    ) -> Path | None:
        """Export one photo; return the output path, or ``None`` on failure."""
        base = self._loader.load(item.path, is_raw=item.is_raw, long_edge=0, full=True)
        if base is None:
            logger.warning("Export could not load %s", item.path)
            return None
        stack = (
            self._store.load(item.photo_id)
            if item.photo_id is not None
            else LayerStack.single()
        )
        rendered = render_stack(base, stack)
        # Resize in float (before quantising) so both 8- and 16-bit exports get the
        # high-quality, full-precision downscale instead of resampling 8-bit pixels.
        rendered = downscale_buffer(rendered, preset.long_edge or 0)
        array = (
            rendered.to_uint16() if preset.effective_bit_depth == 16 else rendered.to_uint8()
        )
        array = apply_watermark(array, preset.watermark)
        dest = Path(dest_dir) / f"{item.path.stem}.{preset.extension}"
        try:
            write_image(array, dest, preset.fmt, preset.quality)
        except (OSError, ValueError):
            logger.exception("Failed to write export %s", dest)
            return None
        return dest

    def export_many(
        self,
        items: list[ExportItem],
        preset: ExportPreset,
        dest_dir: Path,
        progress: ProgressFn | None = None,
    ) -> ExportResult:
        """Export a batch, reporting progress as ``(done, total)``."""
        result = ExportResult()
        total = len(items)
        for index, item in enumerate(items, start=1):
            output = self.export_photo(item, preset, dest_dir)
            if output is not None:
                result.exported += 1
                result.outputs.append(output)
            else:
                result.failed += 1
            if progress is not None:
                progress(index, total)
        logger.info("Exported %d, failed %d to %s", result.exported, result.failed, dest_dir)
        return result
