"""Composition overlay guides drawn over the Develop canvas.

Each overlay is defined as a set of polylines in a normalized ``[0, 1] x [0, 1]``
frame (so the geometry is plain data and testable without Qt). :func:`draw_overlay`
maps that geometry into the displayed image rectangle, applying opacity, 90-degree
rotation, and horizontal/vertical flips — letting a photographer line a shot up
against thirds, the golden ratio, a spiral, diagonals, and more.
"""

from __future__ import annotations

import math
from enum import Enum

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF

Polyline = list[tuple[float, float]]
_PHI = (1 + 5**0.5) / 2
_INV_PHI = 1 / _PHI  # 0.618…
_PHI_LO = 1 - _INV_PHI  # 0.382…


class Overlay(Enum):
    """Composition guide kinds, in menu order. Value is the display label."""

    NONE = "None"
    THIRDS = "Rule of Thirds"
    PHI_GRID = "Golden Ratio (Phi Grid)"
    GOLDEN_SPIRAL = "Golden Spiral"
    GOLDEN_TRIANGLES = "Golden Triangles"
    DIAGONALS = "Diagonals (X)"
    GRID = "Grid"
    CENTER = "Center Cross"
    QUARTERS = "Quarter Thirds"


def _grid_lines(xs: tuple[float, ...], ys: tuple[float, ...]) -> list[Polyline]:
    verticals: list[Polyline] = [[(x, 0.0), (x, 1.0)] for x in xs]
    horizontals: list[Polyline] = [[(0.0, y), (1.0, y)] for y in ys]
    return verticals + horizontals


def _golden_spiral(samples: int = 240, turns: float = 1.5) -> list[Polyline]:
    growth = math.log(_PHI) / (math.pi / 2)  # radius x phi every quarter turn
    raw = []
    theta_max = turns * 2 * math.pi
    for i in range(samples + 1):
        theta = theta_max * i / samples
        radius = math.exp(growth * theta)
        raw.append((radius * math.cos(theta), radius * math.sin(theta)))
    xs = [p[0] for p in raw]
    ys = [p[1] for p in raw]
    width = (max(xs) - min(xs)) or 1.0
    height = (max(ys) - min(ys)) or 1.0
    return [[((x - min(xs)) / width, (y - min(ys)) / height) for x, y in raw]]


def overlay_polylines(overlay: Overlay) -> list[Polyline]:
    """Return the overlay's geometry as normalized ``[0, 1]`` polylines."""
    if overlay is Overlay.THIRDS:
        return _grid_lines((1 / 3, 2 / 3), (1 / 3, 2 / 3))
    if overlay is Overlay.PHI_GRID:
        return _grid_lines((_PHI_LO, _INV_PHI), (_PHI_LO, _INV_PHI))
    if overlay is Overlay.GRID:
        return _grid_lines((0.25, 0.5, 0.75), (0.25, 0.5, 0.75))
    if overlay is Overlay.CENTER:
        return _grid_lines((0.5,), (0.5,))
    if overlay is Overlay.QUARTERS:
        return _grid_lines((0.25, 0.75), (0.25, 0.75))
    if overlay is Overlay.DIAGONALS:
        return [[(0.0, 0.0), (1.0, 1.0)], [(1.0, 0.0), (0.0, 1.0)]]
    if overlay is Overlay.GOLDEN_TRIANGLES:
        return [
            [(0.0, 0.0), (1.0, 1.0)],
            [(1.0, 0.0), (0.5, 0.5)],
            [(0.0, 1.0), (0.5, 0.5)],
        ]
    if overlay is Overlay.GOLDEN_SPIRAL:
        return _golden_spiral()
    return []


def _transform(
    point: tuple[float, float], rotation: int, flip_h: bool, flip_v: bool
) -> tuple[float, float]:
    x, y = point
    if flip_h:
        x = 1.0 - x
    if flip_v:
        y = 1.0 - y
    for _ in range((rotation % 360) // 90):
        x, y = 1.0 - y, x  # rotate 90 degrees within the unit square
    return x, y


def draw_overlay(
    painter: QPainter,
    left: float,
    top: float,
    width: float,
    height: float,
    overlay: Overlay,
    *,
    opacity: float = 0.5,
    rotation: int = 0,
    flip_h: bool = False,
    flip_v: bool = False,
) -> None:
    """Draw ``overlay`` inside the image rect with the given opacity/orientation."""
    if overlay is Overlay.NONE or width < 2 or height < 2:
        return
    polylines = overlay_polylines(overlay)
    if not polylines:
        return
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setOpacity(max(0.0, min(1.0, opacity)))
    shadow = QPen(QColor(0, 0, 0, 130))
    shadow.setWidthF(2.4)
    line = QPen(QColor(255, 255, 255, 235))
    line.setWidthF(1.1)
    for poly in polylines:
        points = [
            QPointF(
                left + tx * width,
                top + ty * height,
            )
            for tx, ty in (_transform(p, rotation, flip_h, flip_v) for p in poly)
        ]
        polygon = QPolygonF(points)
        painter.setPen(shadow)
        painter.drawPolyline(polygon)
        painter.setPen(line)
        painter.drawPolyline(polygon)
    painter.restore()
