"""Tests for the develop settings clipboard."""

from __future__ import annotations

from vibephoto.processing.clipboard import SettingsClipboard
from vibephoto.processing.edit_state import EditState


def test_empty_clipboard() -> None:
    clipboard = SettingsClipboard()
    assert clipboard.has_settings is False
    assert clipboard.paste() is None


def test_copy_then_paste() -> None:
    clipboard = SettingsClipboard()
    clipboard.copy(EditState(exposure=1.0, contrast=20))
    assert clipboard.has_settings
    pasted = clipboard.paste()
    assert pasted is not None and pasted.exposure == 1.0 and pasted.contrast == 20


def test_clipboard_is_snapshotted_and_independent() -> None:
    clipboard = SettingsClipboard()
    source = EditState(exposure=1.0)
    clipboard.copy(source)
    source.exposure = 5.0  # mutating the source must not change the clipboard
    first = clipboard.paste()
    assert first is not None and first.exposure == 1.0
    first.exposure = 9.0  # mutating a paste must not change the clipboard
    second = clipboard.paste()
    assert second is not None and second.exposure == 1.0
