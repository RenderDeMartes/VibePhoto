"""Unified preset loading across formats.

One entry point — :func:`load_preset` — dispatches by file extension to the XMP
or ``.lrtemplate`` reader, so callers (the preset browser, the library) don't care
which format a preset is in.
"""

from __future__ import annotations

from pathlib import Path

from vibephoto.presets.lrtemplate_import import load_lrtemplate
from vibephoto.presets.mapping import PresetParseError
from vibephoto.presets.xmp_import import load_preset as _load_xmp
from vibephoto.processing.edit_state import EditState

#: Preset file extensions Vibe Photo can read.
PRESET_EXTENSIONS = frozenset({".xmp", ".lrtemplate"})


def is_preset(path: Path) -> bool:
    return Path(path).suffix.lower() in PRESET_EXTENSIONS


def load_preset(path: Path) -> tuple[str, EditState]:
    """Return ``(display_name, EditState)`` for any supported preset file."""
    if Path(path).suffix.lower() == ".lrtemplate":
        return load_lrtemplate(path)
    return _load_xmp(path)


__all__ = ["PRESET_EXTENSIONS", "PresetParseError", "is_preset", "load_preset"]
