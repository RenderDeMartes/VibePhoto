"""Undo/redo history for a Develop editing session.

A bounded stack of snapshots with an index, so Ctrl+Z steps back and Ctrl+Y steps
forward. It is generic over any snapshot type that can ``copy()`` itself and
serialise via ``to_dict()`` — used here for the whole :class:`LayerStack`. Pushing
truncates any redo tail (the usual editor semantics) and de-duplicates no-op
pushes, so a burst of slider moves coalesced into one ``push`` is one undo step.
"""

from __future__ import annotations

from typing import Any, Protocol, Self

_MAX_HISTORY = 200


class Snapshot(Protocol):
    """Anything the history can store: copyable and dict-comparable."""

    def to_dict(self) -> dict[str, Any]: ...

    def copy(self) -> Self: ...


class EditHistory[T: Snapshot]:
    """A linear undo/redo stack of edit snapshots."""

    def __init__(self, initial: T) -> None:
        self._stack: list[T] = [initial.copy()]
        self._index = 0

    def reset(self, state: T) -> None:
        """Start a fresh history rooted at ``state`` (e.g. when opening a photo)."""
        self._stack = [state.copy()]
        self._index = 0

    def push(self, state: T) -> None:
        """Record ``state`` as a new step, unless it equals the current step."""
        if state.to_dict() == self._stack[self._index].to_dict():
            return
        del self._stack[self._index + 1 :]  # drop the redo tail
        self._stack.append(state.copy())
        if len(self._stack) > _MAX_HISTORY:
            self._stack.pop(0)
        self._index = len(self._stack) - 1

    @property
    def can_undo(self) -> bool:
        return self._index > 0

    @property
    def can_redo(self) -> bool:
        return self._index < len(self._stack) - 1

    def undo(self) -> T:
        """Step back one edit (no-op at the start) and return that snapshot."""
        if self.can_undo:
            self._index -= 1
        return self._stack[self._index].copy()

    def redo(self) -> T:
        """Step forward one edit (no-op at the end) and return that snapshot."""
        if self.can_redo:
            self._index += 1
        return self._stack[self._index].copy()

    @property
    def current(self) -> T:
        return self._stack[self._index].copy()

    def __len__(self) -> int:
        return len(self._stack)
