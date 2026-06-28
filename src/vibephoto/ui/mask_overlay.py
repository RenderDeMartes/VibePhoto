"""Pure geometry for on-canvas mask editing.

Kept Qt-free so the hit-testing and drag math are unit-testable without synthesising
mouse events. The canvas maps screen ↔ normalised image coordinates and calls these
helpers; everything here works in normalised ``[0, 1]`` space.
"""

from __future__ import annotations

import math

from vibephoto.processing.mask import Mask

#: How close (normalised) a click must be to grab a handle.
HANDLE_TOL = 0.04


def _clamp01(value: float) -> float:
    return min(1.0, max(0.0, value))


def mask_handles(mask: Mask) -> dict[str, tuple[float, float]]:
    """The draggable handles for ``mask`` as ``name -> (nx, ny)`` (empty for brush)."""
    p = mask.params
    if mask.kind == "radial":
        cx, cy = float(p.get("cx", 0.5)), float(p.get("cy", 0.5))
        rx, ry = float(p.get("rx", 0.3)), float(p.get("ry", 0.3))
        return {"center": (cx, cy), "edge_x": (cx + rx, cy), "edge_y": (cx, cy + ry)}
    if mask.kind == "linear":
        return {
            "start": (float(p.get("x0", 0.5)), float(p.get("y0", 0.0))),
            "end": (float(p.get("x1", 0.5)), float(p.get("y1", 0.4))),
        }
    return {}


def hit_handle(mask: Mask, nx: float, ny: float, tol: float = HANDLE_TOL) -> str | None:
    """The nearest handle within ``tol`` of ``(nx, ny)``, or ``None``."""
    best: str | None = None
    best_dist = tol
    for name, (hx, hy) in mask_handles(mask).items():
        dist = math.hypot(nx - hx, ny - hy)
        if dist <= best_dist:
            best_dist = dist
            best = name
    return best


def inside_radial(mask: Mask, nx: float, ny: float) -> bool:
    """Whether ``(nx, ny)`` falls within a radial mask's ellipse (for click-to-move)."""
    if mask.kind != "radial":
        return False
    p = mask.params
    cx, cy = float(p.get("cx", 0.5)), float(p.get("cy", 0.5))
    rx = max(1e-4, float(p.get("rx", 0.3)))
    ry = max(1e-4, float(p.get("ry", 0.3)))
    return ((nx - cx) / rx) ** 2 + ((ny - cy) / ry) ** 2 <= 1.0


def drag_handle(mask: Mask, handle: str, nx: float, ny: float) -> Mask:
    """Return ``mask`` updated by dragging ``handle`` to ``(nx, ny)``."""
    out = mask.copy()
    nx, ny = _clamp01(nx), _clamp01(ny)
    p = dict(out.params)
    if out.kind == "radial":
        cx, cy = float(p.get("cx", 0.5)), float(p.get("cy", 0.5))
        if handle == "center":
            p["cx"], p["cy"] = nx, ny
        elif handle == "edge_x":
            p["rx"] = max(0.02, abs(nx - cx))
        elif handle == "edge_y":
            p["ry"] = max(0.02, abs(ny - cy))
    elif out.kind == "linear":
        if handle == "start":
            p["x0"], p["y0"] = nx, ny
        elif handle == "end":
            p["x1"], p["y1"] = nx, ny
    out.params = p
    return out


def move_radial(mask: Mask, nx: float, ny: float) -> Mask:
    """Recentre a radial mask at ``(nx, ny)`` (drag-inside-to-move)."""
    return drag_handle(mask, "center", nx, ny)


def paint_dab(mask: Mask, nx: float, ny: float, radius: float) -> Mask:
    """Append a brush dab at ``(nx, ny)`` of the given normalised radius."""
    out = mask.copy()
    dabs = list(out.params.get("dabs", []))
    dabs.append([_clamp01(nx), _clamp01(ny), max(0.01, radius), 1.0])
    out.params = {**out.params, "dabs": dabs}
    return out
