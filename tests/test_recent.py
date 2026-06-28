"""Tests for the "Edit Like Last" tracker (:class:`LastEdit`)."""

from __future__ import annotations

from vibephoto.processing.layers import LayerStack
from vibephoto.processing.recent import LastEdit


def test_starts_empty() -> None:
    last = LastEdit()
    assert not last.has_edit
    assert last.photo_id is None
    assert last.stack is None


def test_records_photo_and_stack() -> None:
    last = LastEdit()
    stack = LayerStack.single()
    last.record(42, stack)
    assert last.has_edit
    assert last.photo_id == 42
    assert last.stack is not None
    assert len(last.stack.layers) == 1


def test_stores_and_returns_copies() -> None:
    """Recording copies the stack, and reads hand back copies — no aliasing."""
    last = LastEdit()
    stack = LayerStack.single()
    last.record(1, stack)

    stack.add_layer()  # mutate the original after recording
    assert last.stack is not None
    assert len(last.stack.layers) == 1  # snapshot is unaffected

    out = last.stack
    out.add_layer()  # mutate what we read back
    assert last.stack is not None
    assert len(last.stack.layers) == 1  # internal copy is unaffected


def test_record_overwrites_previous() -> None:
    last = LastEdit()
    last.record(1, LayerStack.single())
    last.record(2, LayerStack.single())
    assert last.photo_id == 2
