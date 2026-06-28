"""Import professional RAW editors ``.xmp`` presets into an :class:`EditState`.

Parses the ``crs:`` (camera-raw-settings) namespace — read from both XML
attributes and nested elements, since presets use either — and hands the flattened
settings to :func:`vibephoto.presets.mapping.to_edit_state` (shared with the
``.lrtemplate`` reader). This is the Phase-5 seam that makes a downloaded
preset apply on Vibe Photo's own engine.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from vibephoto.presets.mapping import PresetParseError, to_edit_state
from vibephoto.processing.edit_state import EditState

__all__ = ["PresetParseError", "edit_state_from_xmp", "load_preset"]

_CRS = "{http://ns.adobe.com/camera-raw-settings/1.0/}"
_RDF = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"


def load_preset(path: Path) -> tuple[str, EditState]:
    """Return ``(display_name, EditState)`` for an XMP preset file."""
    values = _parse(path)
    name = _name(values, fallback=Path(path).stem)
    return name, to_edit_state(values)


def edit_state_from_xmp(path: Path) -> EditState:
    """Convenience: just the :class:`EditState` for a preset file."""
    return to_edit_state(_parse(path))


def _parse(path: Path) -> dict[str, Any]:
    """Flatten a preset's ``crs:`` settings into ``{local_name: value}``.

    Scalars are strings; tone curves become lists of ``"x, y"`` strings.
    """
    try:
        root = ET.fromstring(Path(path).read_text(encoding="utf-8"))
    except (OSError, ET.ParseError) as exc:
        raise PresetParseError(f"Could not parse XMP {path}: {exc}") from exc

    description = root.find(f".//{_RDF}Description")
    if description is None:
        raise PresetParseError(f"No rdf:Description in {path}")

    values: dict[str, Any] = {}
    for key, value in description.attrib.items():
        if key.startswith(_CRS):
            values[key[len(_CRS) :]] = value
    for child in description:
        if not child.tag.startswith(_CRS):
            continue
        local = child.tag[len(_CRS) :]
        seq = child.find(f"{_RDF}Seq")
        alt = child.find(f"{_RDF}Alt")
        if seq is not None:  # ordered sequence (tone curves)
            values[local] = [li.text or "" for li in seq.findall(f"{_RDF}li")]
        elif alt is not None:  # localised alternatives (Name, Group, …)
            item = alt.find(f"{_RDF}li")
            if item is not None and item.text:
                values[local] = item.text.strip()
        elif child.text and child.text.strip():
            values[local] = child.text.strip()
    return values


def _name(values: dict[str, Any], *, fallback: str) -> str:
    """A friendly display name.

    Presets often store a terse ``crs:Name`` (e.g. ``"6"``) under a ``crs:Group``
    (e.g. ``"Bali"``); combine them unless the name already includes the group.
    Falls back to the file stem when no name is present.
    """
    name = _text(values.get("Name"))
    group = _text(values.get("Group"))
    if name and group and not name.lower().startswith(group.lower()):
        return f"{group} {name}"
    return name or fallback


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else ""
