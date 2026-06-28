"""Tests for the Qt-free on-canvas mask-edit geometry."""

from __future__ import annotations

from vibephoto.processing.mask import Mask
from vibephoto.ui.mask_overlay import (
    drag_handle,
    hit_handle,
    inside_radial,
    mask_handles,
    paint_dab,
)


def test_radial_handles_and_hit() -> None:
    mask = Mask.radial(0.5, 0.5, 0.3)
    handles = mask_handles(mask)
    assert handles["center"] == (0.5, 0.5)
    assert handles["edge_x"] == (0.8, 0.5)
    assert hit_handle(mask, 0.8, 0.5) == "edge_x"
    assert hit_handle(mask, 0.5, 0.5) == "center"
    assert hit_handle(mask, 0.1, 0.1) is None  # nothing nearby


def test_radial_drag_moves_and_resizes() -> None:
    mask = Mask.radial(0.5, 0.5, 0.3)
    moved = drag_handle(mask, "center", 0.4, 0.6)
    assert moved.params["cx"] == 0.4 and moved.params["cy"] == 0.6
    resized = drag_handle(mask, "edge_x", 0.9, 0.5)
    assert abs(resized.params["rx"] - 0.4) < 1e-6
    assert inside_radial(mask, 0.5, 0.5) and not inside_radial(mask, 0.95, 0.95)


def test_linear_handle_drag() -> None:
    mask = Mask.gradient("vertical", 0.0, 0.4)
    handles = mask_handles(mask)
    assert handles["start"] == (0.5, 0.0)
    out = drag_handle(mask, "end", 0.5, 0.7)
    assert out.params["y1"] == 0.7


def test_drag_clamps_to_unit_square() -> None:
    mask = Mask.radial()
    out = drag_handle(mask, "center", 1.5, -0.3)
    assert out.params["cx"] == 1.0 and out.params["cy"] == 0.0


def test_paint_dab_appends() -> None:
    mask = Mask.brush()
    one = paint_dab(mask, 0.25, 0.75, 0.05)
    two = paint_dab(one, 0.30, 0.70, 0.05)
    assert len(two.params["dabs"]) == 2
    assert two.params["dabs"][0][:2] == [0.25, 0.75]
