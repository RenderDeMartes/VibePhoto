"""Tracks the most recently edited photo, for "Edit Like Last".

A tiny app-wide service that remembers the last photo whose (non-trivial) edit was
committed, plus a copy of its :class:`LayerStack`. "Edit Like Last" then applies
that stack to the photo currently open — the quick way to carry a look across a
shoot.
"""

from __future__ import annotations

from vibephoto.processing.layers import LayerStack


class LastEdit:
    """Holds the most recently committed edit (photo id + its layer stack)."""

    def __init__(self) -> None:
        self._photo_id: int | None = None
        self._stack: LayerStack | None = None

    def record(self, photo_id: int, stack: LayerStack) -> None:
        self._photo_id = photo_id
        self._stack = stack.copy()

    @property
    def photo_id(self) -> int | None:
        return self._photo_id

    @property
    def stack(self) -> LayerStack | None:
        return self._stack.copy() if self._stack is not None else None

    @property
    def has_edit(self) -> bool:
        return self._stack is not None
