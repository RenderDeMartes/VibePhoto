"""Pure geometry for the on-canvas crop tool.

Qt-free so hit-testing and edge/corner dragging are unit-testable. A crop rect is a
normalised ``(left, top, right, bottom)`` in ``[0, 1]``; the canvas maps it to
screen pixels and calls these helpers.
"""

from __future__ import annotations

Rect = tuple[float, float, float, float]

HANDLE_TOL = 0.035
#: A point outside the box but within this radius of a corner is the rotate zone.
ROTATE_TOL = 0.18
_MIN_SIZE = 0.05  # smallest allowed crop extent (5% of the frame)
_CORNERS = ("tl", "tr", "bl", "br")

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


def in_rotate_zone(rect: Rect, nx: float, ny: float, tol: float = ROTATE_TOL) -> bool:
    """True if ``(nx, ny)`` is *outside* the box but near a corner → rotate, not pan."""
    if inside_crop(rect, nx, ny):
        return False
    for hx, hy in (crop_handles(rect)[name] for name in _CORNERS):
        if ((nx - hx) ** 2 + (ny - hy) ** 2) ** 0.5 <= tol:
            return True
    return False


def _order_clamp(left: float, top: float, right: float, bottom: float) -> Rect:
    """Sort the edges, clamp to the frame, and enforce the minimum extent."""
    if left > right:
        left, right = right, left
    if top > bottom:
        top, bottom = bottom, top
    left, top, right, bottom = _clamp01(left), _clamp01(top), _clamp01(right), _clamp01(bottom)
    if right - left < _MIN_SIZE:
        right = min(1.0, left + _MIN_SIZE)
        left = right - _MIN_SIZE
    if bottom - top < _MIN_SIZE:
        bottom = min(1.0, top + _MIN_SIZE)
        top = bottom - _MIN_SIZE
    return (left, top, right, bottom)


def drag_crop_handle(
    rect: Rect,
    handle: str,
    nx: float,
    ny: float,
    *,
    lock_aspect: bool = False,
    from_center: bool = False,
) -> Rect:
    """Return ``rect`` with ``handle`` dragged to ``(nx, ny)`` (clamped, min size).

    ``lock_aspect`` (Shift) keeps the current width:height ratio; ``from_center``
    (Alt) anchors the opposite side to the box centre so it scales symmetrically.
    """
    left, top, right, bottom = rect
    nx, ny = _clamp01(nx), _clamp01(ny)
    cx, cy = (left + right) / 2.0, (top + bottom) / 2.0
    height = bottom - top
    aspect = (right - left) / height if height > 1e-6 else 1.0

    has_l, has_r, has_t = "l" in handle, "r" in handle, "t" in handle

    if handle in _CORNERS:
        ox = right if has_l else left  # opposite (anchored) corner
        oy = bottom if has_t else top
        if from_center:
            ox, oy = cx, cy
        mx, my = nx, ny
        if lock_aspect:
            dx, dy = mx - ox, my - oy
            w, h = abs(dx), abs(dy)
            if w >= h * aspect:
                h = w / aspect
            else:
                w = h * aspect
            mx = ox + (w if dx >= 0 else -w)
            my = oy + (h if dy >= 0 else -h)
        if from_center:
            hx, hy = abs(mx - cx), abs(my - cy)
            return _order_clamp(cx - hx, cy - hy, cx + hx, cy + hy)
        return _order_clamp(ox, oy, mx, my)

    if has_l or has_r:  # vertical edge → width
        if has_l:
            new_left, new_right = nx, (2 * cx - nx if from_center else right)
        else:
            new_left, new_right = (2 * cx - nx if from_center else left), nx
        new_top, new_bottom = top, bottom
        if lock_aspect:
            half = abs(new_right - new_left) / aspect / 2.0
            new_top, new_bottom = cy - half, cy + half
    else:  # horizontal edge → height
        if has_t:
            new_top, new_bottom = ny, (2 * cy - ny if from_center else bottom)
        else:
            new_top, new_bottom = (2 * cy - ny if from_center else top), ny
        new_left, new_right = left, right
        if lock_aspect:
            half = abs(new_bottom - new_top) * aspect / 2.0
            new_left, new_right = cx - half, cx + half
    return _order_clamp(new_left, new_top, new_right, new_bottom)


def move_crop(rect: Rect, dx: float, dy: float) -> Rect:
    """Translate the whole rect by ``(dx, dy)``, keeping it inside the frame."""
    left, top, right, bottom = rect
    width, height = right - left, bottom - top
    dx = max(-left, min(1.0 - right, dx))
    dy = max(-top, min(1.0 - bottom, dy))
    return (left + dx, top + dy, left + dx + width, top + dy + height)
