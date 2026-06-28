"""Pure geometry for the on-canvas crop tool.

Qt-free so hit-testing and edge/corner dragging are unit-testable. A crop rect is a
normalised ``(left, top, right, bottom)`` in ``[0, 1]``; the canvas maps it to
screen pixels and calls these helpers.
"""

from __future__ import annotations

Rect = tuple[float, float, float, float]

HANDLE_TOL = 0.035
_MIN_SIZE = 0.05  # smallest allowed crop extent (5% of the frame)

#: The eight crop handles as fractions of the rect (corners + edge midpoints).
_HANDLES: dict[str, tuple[float, float]] = {
    "tl": (0.0, 0.0),
    "tr": (1.0, 0.0),
    "bl": (0.0, 1.0),
    "br": (1.0, 1.0),
    "t": (0.5, 0.0),
    "b": (0.5, 1.0),
    "l": (0.0, 0.5),
    "r": (1.0, 0.5),
}


def _clamp01(v: float) -> float:
    return min(1.0, max(0.0, v))


def crop_handles(rect: Rect) -> dict[str, tuple[float, float]]:
    """Handle positions in normalised image coordinates."""
    left, top, right, bottom = rect
    out: dict[str, tuple[float, float]] = {}
    for name, (fx, fy) in _HANDLES.items():
        out[name] = (left + fx * (right - left), top + fy * (bottom - top))
    return out


def hit_crop_handle(rect: Rect, nx: float, ny: float, tol: float = HANDLE_TOL) -> str | None:
    """Nearest crop handle within ``tol`` of ``(nx, ny)``, else ``None``."""
    best: str | None = None
    best_dist = tol
    for name, (hx, hy) in crop_handles(rect).items():
        dist = ((nx - hx) ** 2 + (ny - hy) ** 2) ** 0.5
        if dist <= best_dist:
            best_dist = dist
            best = name
    return best


def inside_crop(rect: Rect, nx: float, ny: float) -> bool:
    left, top, right, bottom = rect
    return left <= nx <= right and top <= ny <= bottom


def drag_crop_handle(rect: Rect, handle: str, nx: float, ny: float) -> Rect:
    """Return ``rect`` with ``handle`` dragged to ``(nx, ny)`` (clamped, min size)."""
    left, top, right, bottom = rect
    nx, ny = _clamp01(nx), _clamp01(ny)
    if "l" in handle:
        left = min(nx, right - _MIN_SIZE)
    if "r" in handle:
        right = max(nx, left + _MIN_SIZE)
    if "t" in handle:
        top = min(ny, bottom - _MIN_SIZE)
    if "b" in handle:
        bottom = max(ny, top + _MIN_SIZE)
    return (left, top, right, bottom)


def move_crop(rect: Rect, dx: float, dy: float) -> Rect:
    """Translate the whole rect by ``(dx, dy)``, keeping it inside the frame."""
    left, top, right, bottom = rect
    width, height = right - left, bottom - top
    dx = max(-left, min(1.0 - right, dx))
    dy = max(-top, min(1.0 - bottom, dy))
    return (left + dx, top + dy, left + dx + width, top + dy + height)
