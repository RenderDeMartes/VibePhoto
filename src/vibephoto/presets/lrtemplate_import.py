"""Import legacy ``.lrtemplate`` presets (Lua tables) into an EditState.

Older professional RAW editors develop presets are Lua source files of the form::

    s = {
        title = "My Look",
        value = { settings = { Exposure2012 = 0.5, Contrast2012 = 25,
                               ToneCurvePV2012 = { 0, 0, 255, 255 }, ... } },
    }

The ``settings`` table uses the same ``crs:`` parameter names as XMP, so this
module only needs to *read* the Lua table — it extracts the top-level scalar and
tone-curve entries of ``settings`` (nested tables such as local-adjustment masks
are skipped) and hands them to the shared mapping. A full Lua interpreter is not
needed; a brace-matching scan is enough and avoids any code execution.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from vibephoto.presets.mapping import PresetParseError, to_edit_state
from vibephoto.processing.edit_state import EditState

_KEY = re.compile(r"([A-Za-z_]\w*)\s*=\s*")
_BRACKET_KEY = re.compile(r'\[\s*"([^"]*)"\s*\]\s*=\s*')
_SCALAR = re.compile(r"""(-?\d+\.?\d*|true|false|nil|"[^"]*"|'[^']*')""")
_NUMBER = re.compile(r"-?\d+\.?\d*")


def load_lrtemplate(path: Path) -> tuple[str, EditState]:
    """Return ``(display_name, EditState)`` for a ``.lrtemplate`` preset."""
    text = _read(path)
    settings = _settings_block(text)
    if settings is None:
        raise PresetParseError(f"No develop settings table in {path}")
    name = _title(text) or Path(path).stem
    return name, to_edit_state(_top_level_entries(settings))


def edit_state_from_lrtemplate(path: Path) -> EditState:
    return load_lrtemplate(path)[1]


def _read(path: Path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise PresetParseError(f"Could not read {path}: {exc}") from exc


def _title(text: str) -> str:
    for key in ("title", "internalName"):
        match = re.search(key + r'\s*=\s*"([^"]*)"', text)
        if match and match.group(1).strip():
            return match.group(1).strip()
    return ""


def _settings_block(text: str) -> str | None:
    """The inner text of the first ``settings = { … }`` table, or ``None``."""
    match = re.search(r"settings\s*=\s*\{", text)
    if match is None:
        return None
    inner, _ = _balanced(text, match.end() - 1)
    return inner


def _balanced(text: str, start: int) -> tuple[str, int]:
    """Inner text of the ``{…}`` block at ``start`` and the index past its close."""
    depth = 0
    index = start
    length = len(text)
    while index < length:
        char = text[index]
        if char in "\"'":
            index = _skip_string(text, index)
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1 : index], index + 1
        index += 1
    return text[start + 1 :], length


def _skip_string(text: str, start: int) -> int:
    quote = text[start]
    index = start + 1
    length = len(text)
    while index < length:
        if text[index] == "\\":
            index += 2
            continue
        if text[index] == quote:
            return index + 1
        index += 1
    return length


def _top_level_entries(block: str) -> dict[str, Any]:
    """Scalar and tone-curve entries at the top level of ``settings`` (depth 0).

    Nested tables (e.g. mask groups) are skipped, so their keyed values can't
    shadow the global look settings.
    """
    out: dict[str, Any] = {}
    index = 0
    depth = 0
    length = len(block)
    while index < length:
        char = block[index]
        if char in "\"'":
            index = _skip_string(block, index)
            continue
        if char == "{":
            depth += 1
            index += 1
            continue
        if char == "}":
            depth -= 1
            index += 1
            continue
        if depth == 0:
            key, after = _match_key(block, index)
            if key is not None:
                index = _read_entry(block, after, key, out)
                continue
        index += 1
    return out


def _match_key(block: str, index: int) -> tuple[str | None, int]:
    if block[index] == "[":
        match = _BRACKET_KEY.match(block, index)
        if match:
            return match.group(1), match.end()
        return None, index
    match = _KEY.match(block, index)
    if match:
        return match.group(1), match.end()
    return None, index


def _read_entry(block: str, after: int, key: str, out: dict[str, Any]) -> int:
    if after < len(block) and block[after] == "{":  # table value (tone curve / masks)
        inner, end = _balanced(block, after)
        out[key] = [float(n) for n in _NUMBER.findall(inner)]
        return end
    scalar = _SCALAR.match(block, after)
    if scalar:
        raw = scalar.group(1)
        out[key] = raw[1:-1] if raw[:1] in "\"'" else raw
        return scalar.end()
    return after
