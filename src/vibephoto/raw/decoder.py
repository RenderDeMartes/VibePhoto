"""RAW decoding behind a pluggable decoder registry.

The rest of the application asks only "give me this RAW's preview / dimensions"
or "decode this RAW" and never imports rawpy directly. A :class:`RawDecoder`
Protocol lets new backends (OpenImageIO, per-camera shims) register without
touching callers, and keeps rawpy an *optional* dependency: if the ``raw`` extra
is not installed the registry is simply empty and callers degrade to placeholders
— preserving the headless-core invariant (``raw`` never imports ``ui``).

Two operations cover Phase 3:

* :meth:`RawDecoder.inspect` — a cheap, import-time read returning the embedded
  JPEG preview (fast path for the Library grid + EXIF) plus the master image's
  pixel dimensions and LibRaw orientation flag.
* :meth:`RawDecoder.decode` — a full LibRaw demosaic to a display-oriented RGB
  raster, the foundation the Develop pipeline (Phase 4) renders from.

Designed in: ``docs/06-processing-engine.md`` (RAW Decode stage).
"""

from __future__ import annotations

import io
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from vibephoto.raw.formats import RAW_EXTENSIONS

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RawInspection:
    """Cheap, import-time facts about a RAW file.

    ``preview`` is the embedded JPEG (already encoded bytes, ready to thumbnail or
    read EXIF from) or ``None`` when the file has no usable embedded preview.
    ``width``/``height`` are the *master* image's pixel dimensions (unrotated, as
    LibRaw reports them — the same convention Pillow uses for rendered files), and
    ``flip`` is LibRaw's orientation code (0/3/5/6).
    """

    preview: bytes | None
    width: int
    height: int
    flip: int
    #: LibRaw colour calibration, for as-shot colour-temperature estimation.
    camera_wb: tuple[float, ...] | None = None
    xyz_to_cam: tuple[tuple[float, ...], ...] | None = None


@dataclass(frozen=True, slots=True)
class RawImage:
    """A fully decoded, display-oriented **16-bit** RGB raster from a RAW file.

    16-bit (not 8-bit) so the develop pipeline edits the real sensor data with its
    tonal headroom intact, rather than the camera's flattened JPEG preview.
    """

    rgb: NDArray[np.uint16]
    width: int
    height: int


@runtime_checkable
class RawDecoder(Protocol):
    """Decodes one family of RAW formats. Implementations must never raise from
    :meth:`inspect`/:meth:`decode` — they return ``None`` on any failure so a
    single bad file cannot stall an import or a grid repaint."""

    name: str

    def handles(self, ext: str) -> bool:
        """Whether this decoder handles the given extension (with or without dot)."""
        ...

    def inspect(self, path: Path) -> RawInspection | None:
        """Embedded preview + master dimensions, in a single file open."""
        ...

    def decode(self, path: Path, *, half_size: bool = False) -> RawImage | None:
        """Full LibRaw demosaic to a display-oriented 16-bit RGB array.

        ``half_size`` requests a faster half-resolution demosaic (for live
        previews); the full decode is used for 1:1 zoom and export.
        """
        ...


class RawpyDecoder:
    """LibRaw-backed decoder (via rawpy) covering every target RAW format.

    rawpy is imported in ``__init__`` so :func:`default_registry` can detect its
    absence (``ImportError``) and leave RAW support disabled rather than failing
    at import time.
    """

    name = "rawpy"

    def __init__(self) -> None:
        # Imported lazily so rawpy stays an optional dependency (the `raw` extra).
        import rawpy

        self._rawpy = rawpy

    def handles(self, ext: str) -> bool:
        return ext.lstrip(".").lower() in RAW_EXTENSIONS

    def inspect(self, path: Path) -> RawInspection | None:
        rawpy = self._rawpy
        try:
            with rawpy.imread(str(path)) as raw:
                sizes = raw.sizes
                preview = self._extract_preview(raw)
                return RawInspection(
                    preview=preview,
                    width=int(sizes.width),
                    height=int(sizes.height),
                    flip=int(sizes.flip),
                    camera_wb=tuple(float(v) for v in raw.camera_whitebalance),
                    xyz_to_cam=tuple(
                        tuple(float(v) for v in row) for row in raw.rgb_xyz_matrix
                    ),
                )
        except (rawpy.LibRawError, OSError, ValueError):
            logger.debug("RAW inspect failed for %s", path, exc_info=True)
            return None

    def decode(self, path: Path, *, half_size: bool = False) -> RawImage | None:
        rawpy = self._rawpy
        try:
            with rawpy.imread(str(path)) as raw:
                # Scene-linear 16-bit demosaic: camera white balance applied, but NO
                # tone curve (gamma 1) and no auto-brighten — the develop pipeline
                # does exposure/tone in linear and tone-maps to display itself. This
                # is what makes editing behave like developing a RAW, not a JPEG.
                #
                # highlight_mode=Blend (not LibRaw's default Clip): a channel that
                # clips at sensor saturation is reconstructed by blending the
                # unclipped channels' detail instead of being flattened to white.
                # This preserves recoverable highlight detail (a bright sky, a
                # window) for the linear Highlights/Recovery stages downstream — the
                # difference between "recover the blown highlights" working like
                # professional RAW editors and there being nothing left to recover.
                rgb = raw.postprocess(
                    use_camera_wb=True,
                    output_bps=16,
                    gamma=(1.0, 1.0),
                    no_auto_bright=True,
                    highlight_mode=rawpy.HighlightMode.Blend,
                    half_size=half_size,
                )
        except (rawpy.LibRawError, OSError, ValueError, MemoryError):
            logger.debug("RAW decode failed for %s", path, exc_info=True)
            return None
        return RawImage(rgb=rgb, width=int(rgb.shape[1]), height=int(rgb.shape[0]))

    def _extract_preview(self, raw: Any) -> bytes | None:
        rawpy = self._rawpy
        try:
            thumb = raw.extract_thumb()
        except (rawpy.LibRawNoThumbnailError, rawpy.LibRawUnsupportedThumbnailError):
            return self._render_preview(raw)
        if thumb.format == rawpy.ThumbFormat.JPEG:
            return bytes(thumb.data)  # already a JPEG file; write/read as-is
        return _ndarray_to_jpeg(thumb.data)  # BITMAP -> encode

    def _render_preview(self, raw: Any) -> bytes | None:
        """Fallback when no embedded thumbnail exists: a fast half-size decode."""
        try:
            rgb = raw.postprocess(use_camera_wb=True, half_size=True, output_bps=8)
        except (self._rawpy.LibRawError, MemoryError):
            return None
        return _ndarray_to_jpeg(rgb)


class DecoderRegistry:
    """Ordered set of decoders; the first that ``handles`` an extension wins."""

    def __init__(self, decoders: Iterable[RawDecoder] = ()) -> None:
        self._decoders: list[RawDecoder] = list(decoders)

    def register(self, decoder: RawDecoder) -> None:
        self._decoders.append(decoder)

    def decoder_for(self, ext: str) -> RawDecoder | None:
        bare = ext.lstrip(".").lower()
        for decoder in self._decoders:
            if decoder.handles(bare):
                return decoder
        return None

    @property
    def available(self) -> bool:
        """True when at least one decoder is registered (i.e. RAW is supported)."""
        return bool(self._decoders)

    @property
    def decoders(self) -> tuple[RawDecoder, ...]:
        return tuple(self._decoders)


def default_registry() -> DecoderRegistry:
    """Build the default registry, including rawpy when the ``raw`` extra is installed."""
    registry = DecoderRegistry()
    try:
        registry.register(RawpyDecoder())
    except ImportError:
        logger.info(
            "rawpy not installed; RAW decoding disabled — install the 'raw' extra "
            "for CR2/CR3/NEF/ARW/DNG/RAF/RW2/ORF/PEF support"
        )
    return registry


def _ndarray_to_jpeg(arr: NDArray[np.uint8], quality: int = 90) -> bytes | None:
    """Encode an ``(H, W, 3)`` uint8 array as JPEG bytes."""
    try:
        buffer = io.BytesIO()
        Image.fromarray(arr).convert("RGB").save(buffer, format="JPEG", quality=quality)
    except (ValueError, OSError, TypeError):
        return None
    return buffer.getvalue()
