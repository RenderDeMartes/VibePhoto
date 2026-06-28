"""Tests for the Qt-free on-canvas crop geometry."""

from __future__ import annotations

import pytest

from vibephoto.ui.crop_overlay import (
    crop_handles,
    drag_crop_handle,
    hit_crop_handle,
    inside_crop,
    move_crop,
)


def test_handles_and_hit() -> None:
    rect = (0.2, 0.2, 0.8, 0.8)
    handles = crop_handles(rect)
    assert handles["tl"] == (0.2, 0.2)
    assert handles["br"] == (0.8, 0.8)
    assert handles["t"] == (0.5, 0.2)
    assert hit_crop_handle(rect, 0.2, 0.2) == "tl"
    assert hit_crop_handle(rect, 0.5, 0.5) is None  # centre is not a handle


def test_drag_corner_resizes_with_min_size() -> None:
    rect = (0.2, 0.2, 0.8, 0.8)
    out = drag_crop_handle(rect, "tl", 0.4, 0.5)
    assert out[0] == 0.4 and out[1] == 0.5 and out[2] == 0.8
    # Cannot collapse past the minimum size.
    squashed = drag_crop_handle(rect, "tl", 0.79, 0.79)
    assert squashed[2] - squashed[0] >= 0.04 and squashed[3] - squashed[1] >= 0.04


def test_drag_edge_moves_only_that_side() -> None:
    rect = (0.2, 0.2, 0.8, 0.8)
    out = drag_crop_handle(rect, "r", 0.6, 0.99)
    assert out == (0.2, 0.2, 0.6, 0.8)  # only the right edge moved


def test_move_keeps_rect_in_frame() -> None:
    rect = (0.0, 0.0, 0.4, 0.4)
    moved = move_crop(rect, 0.2, 0.1)
    assert moved == pytest.approx((0.2, 0.1, 0.6, 0.5))
    clamped = move_crop(rect, -0.5, -0.5)  # cannot go past the edge
    assert clamped == pytest.approx((0.0, 0.0, 0.4, 0.4))
    assert inside_crop(rect, 0.1, 0.1) and not inside_crop(rect, 0.9, 0.9)
