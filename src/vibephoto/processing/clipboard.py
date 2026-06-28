"""A small in-memory clipboard for develop settings.

Holds one :class:`EditState` so a photographer can copy a look from one photo and
paste it onto others (the whole edit at once, the conventional Copy/Paste Settings).
A single app-wide instance is shared via the DI container, so the Develop panel
and the Library both read and write the same clipboard.
"""

from __future__ import annotations

from vibephoto.processing.edit_state import EditState


class SettingsClipboard:
    """Stores a copied :class:`EditState` for paste onto other photos."""

    def __init__(self) -> None:
        self._state: EditState | None = None

    def copy(self, state: EditState) -> None:
        self._state = state.copy()

    def paste(self) -> EditState | None:
        """Return a fresh copy of the held settings, or ``None`` if empty."""
        return self._state.copy() if self._state is not None else None

    @property
    def has_settings(self) -> bool:
        return self._state is not None
