"""Tests for the Qt-free on-canvas crop geometry."""

from __future__ import annotations

import pytest

from vibephoto.ui.crop_overlay import (
    crop_handles,
    drag_crop_handle,
    hit_crop_handle,
    in_rotate_zone,
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


def test_drag_corner_locks_aspect_with_shift() -> None:
    rect = (0.2, 0.2, 0.8, 0.8)  # square → aspect 1
    out = drag_crop_handle(rect, "br", 0.9, 0.7, lock_aspect=True)
    width, height = out[2] - out[0], out[3] - out[1]
    assert width == pytest.approx(height)  # ratio preserved
    assert (out[0], out[1]) == pytest.approx((0.2, 0.2))  # opposite corner anchored


def test_drag_corner_scales_from_center_with_alt() -> None:
    rect = (0.2, 0.2, 0.8, 0.8)
    out = drag_crop_handle(rect, "br", 0.7, 0.7, from_center=True)
    cx, cy = (out[0] + out[2]) / 2, (out[1] + out[3]) / 2
    assert (cx, cy) == pytest.approx((0.5, 0.5))  # centre held fixed
    assert out == pytest.approx((0.3, 0.3, 0.7, 0.7))  # symmetric


def test_drag_corner_alt_and_shift_combined() -> None:
    rect = (0.2, 0.2, 0.8, 0.8)
    out = drag_crop_handle(rect, "br", 0.9, 0.7, lock_aspect=True, from_center=True)
    cx, cy = (out[0] + out[2]) / 2, (out[1] + out[3]) / 2
    assert (cx, cy) == pytest.approx((0.5, 0.5))
    assert (out[2] - out[0]) == pytest.approx(out[3] - out[1])


def test_drag_edge_from_center_mirrors() -> None:
    rect = (0.2, 0.2, 0.8, 0.8)
    out = drag_crop_handle(rect, "r", 0.7, 0.5, from_center=True)
    assert out == pytest.approx((0.3, 0.2, 0.7, 0.8))  # left edge mirrored the right


def test_drag_edge_lock_aspect_grows_perpendicular() -> None:
    rect = (0.2, 0.2, 0.8, 0.8)  # aspect 1
    out = drag_crop_handle(rect, "r", 0.7, 0.5, lock_aspect=True)
    assert (out[2] - out[0]) == pytest.approx(out[3] - out[1])  # stays square


def test_rotate_zone_only_near_corners() -> None:
    rect = (0.2, 0.2, 0.8, 0.8)
    assert in_rotate_zone(rect, 0.85, 0.85)  # just outside the br corner
    assert not in_rotate_zone(rect, 0.5, 0.5)  # inside the box
    assert not in_rotate_zone(rect, 0.5, 0.98)  # outside but mid-edge, far from a corner


def test_move_keeps_rect_in_frame() -> None:
    rect = (0.0, 0.0, 0.4, 0.4)
    moved = move_crop(rect, 0.2, 0.1)
    assert moved == pytest.approx((0.2, 0.1, 0.6, 0.5))
    clamped = move_crop(rect, -0.5, -0.5)  # cannot go past the edge
    assert clamped == pytest.approx((0.0, 0.0, 0.4, 0.4))
    assert inside_crop(rect, 0.1, 0.1) and not inside_crop(rect, 0.9, 0.9)
