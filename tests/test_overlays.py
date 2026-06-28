"""Geometry tests for the composition overlays.

The overlay geometry is plain normalized data, so it is testable without a Qt
event loop — only the import needs PySide6 (skipped if it is absent).
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from vibephoto.ui.overlays import Overlay, _transform, overlay_polylines


def _in_unit_square(polylines: list[list[tuple[float, float]]]) -> bool:
    return all(0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 for line in polylines for x, y in line)


def test_none_has_no_geometry() -> None:
    assert overlay_polylines(Overlay.NONE) == []


@pytest.mark.parametrize("overlay", [o for o in Overlay if o is not Overlay.NONE])
def test_every_overlay_is_normalized(overlay: Overlay) -> None:
    polylines = overlay_polylines(overlay)
    assert polylines, f"{overlay} produced no geometry"
    assert _in_unit_square(polylines)


def test_thirds_has_four_lines_at_thirds() -> None:
    lines = overlay_polylines(Overlay.THIRDS)
    assert len(lines) == 4  # two vertical, two horizontal
    xs = {round(line[0][0], 3) for line in lines if line[0][0] == line[1][0]}
    assert xs == {round(1 / 3, 3), round(2 / 3, 3)}


def test_diagonals_cross_corner_to_corner() -> None:
    lines = overlay_polylines(Overlay.DIAGONALS)
    assert [(0.0, 0.0), (1.0, 1.0)] in lines
    assert [(1.0, 0.0), (0.0, 1.0)] in lines


def test_golden_spiral_is_a_single_dense_polyline() -> None:
    lines = overlay_polylines(Overlay.GOLDEN_SPIRAL)
    assert len(lines) == 1
    assert len(lines[0]) > 50  # sampled smoothly


def test_transform_identity() -> None:
    assert _transform((0.25, 0.75), 0, False, False) == (0.25, 0.75)


def test_transform_flip_horizontal() -> None:
    assert _transform((0.25, 0.75), 0, True, False) == (0.75, 0.75)


def test_transform_flip_vertical() -> None:
    assert _transform((0.25, 0.75), 0, False, True) == (0.25, 0.25)


def test_transform_rotate_90() -> None:
    x, y = _transform((0.25, 0.75), 90, False, False)
    assert (round(x, 6), round(y, 6)) == (0.25, 0.25)


def test_transform_rotate_360_is_identity() -> None:
    assert _transform((0.3, 0.6), 360, False, False) == (0.3, 0.6)


def test_transform_keeps_points_in_unit_square() -> None:
    for rotation in (0, 90, 180, 270):
        x, y = _transform((0.2, 0.9), rotation, True, True)
        assert 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0
