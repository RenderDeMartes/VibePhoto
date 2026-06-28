"""Preset layer — preset model, library, and XMP import/export.

Manages preset packs, folders, favourites, and the conversion layer that maps
industry-standard XMP preset parameters onto Vibe Photo processing
nodes, so photographers can download presets online and apply them
immediately. Presets are stored as portable JSON and round-trip to XMP.

Depends on: ``core``, ``processing`` (node parameter schema), ``metadata``.
Never imports ``ui``.
Designed in: ``docs/08-preset-system.md``.
Built in: Phase 5.
"""

from __future__ import annotations

from vibephoto.presets.library import GENERAL_GROUP, PresetLibrary
from vibephoto.presets.loaders import PRESET_EXTENSIONS, is_preset, load_preset
from vibephoto.presets.lrtemplate_import import load_lrtemplate
from vibephoto.presets.mapping import PresetParseError, to_edit_state
from vibephoto.presets.xmp_import import edit_state_from_xmp

__all__ = [
    "GENERAL_GROUP",
    "PRESET_EXTENSIONS",
    "PresetLibrary",
    "PresetParseError",
    "edit_state_from_xmp",
    "is_preset",
    "load_lrtemplate",
    "load_preset",
    "to_edit_state",
]
