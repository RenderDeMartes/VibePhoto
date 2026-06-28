"""Tests for the Develop undo/redo history."""

from __future__ import annotations

from vibephoto.processing.edit_state import EditState
from vibephoto.processing.history import EditHistory


def test_starts_with_nothing_to_undo() -> None:
    history = EditHistory(EditState())
    assert not history.can_undo
    assert not history.can_redo


def test_undo_and_redo_walk_the_stack() -> None:
    history = EditHistory(EditState())
    history.push(EditState(exposure=1.0))
    history.push(EditState(exposure=2.0))
    assert history.can_undo and not history.can_redo

    assert history.undo().exposure == 1.0
    assert history.undo().exposure == 0.0
    assert not history.can_undo
    assert history.redo().exposure == 1.0
    assert history.redo().exposure == 2.0
    assert not history.can_redo


def test_push_deduplicates_identical_state() -> None:
    history = EditHistory(EditState(exposure=1.0))
    history.push(EditState(exposure=1.0))  # identical to current
    assert len(history) == 1


def test_new_edit_truncates_the_redo_tail() -> None:
    history = EditHistory(EditState())
    history.push(EditState(exposure=1.0))
    history.push(EditState(exposure=2.0))
    history.undo()  # back to exposure 1.0, redo available
    assert history.can_redo
    history.push(EditState(contrast=5.0))  # branch off — redo tail dropped
    assert not history.can_redo
    assert history.current.contrast == 5.0


def test_reset_clears_history() -> None:
    history = EditHistory(EditState(exposure=1.0))
    history.push(EditState(exposure=2.0))
    history.reset(EditState(contrast=9.0))
    assert not history.can_undo
    assert history.current.contrast == 9.0
