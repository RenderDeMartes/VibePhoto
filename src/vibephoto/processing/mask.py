"""Local-adjustment masks — where an adjustment layer applies.

A :class:`Mask` describes a region in **normalised** image coordinates ``[0, 1]``,
so the same mask rasterises identically on the live low-res proxy and the
full-resolution render. A layer can carry several masks that combine (add /
subtract, like the union/intersection of mask components in a pro editor): the
layer's developed pixels are then blended back over its input by the combined
coverage, so the edit is *local*.

Three vector mask kinds ship here — ``radial`` (elliptical), ``linear`` (graduated),
and ``brush`` (feathered circular dabs). All rasterise to a float coverage map in
``[0, 1]``. An ``object`` (subject/sky select) kind is planned but needs a
segmentation model and is not implemented yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from vibephoto.processing.color import Array

_KINDS = ("radial", "linear", "brush")


def _smoothstep(values: np.ndarray) -> Array:
    t = np.clip(np.asarray(values, dtype=np.float32), 0.0, 1.0)
    out: Array = (t * t * (3.0 - 2.0 * t)).astype(np.float32)
    return out


def _grid(height: int, width: int) -> tuple[Array, Array]:
    """Normalised X, Y coordinate grids in ``[0, 1]`` (shape ``(H, W)``)."""
    ys = (np.arange(height, dtype=np.float32) + 0.5) / height
    xs = (np.arange(width, dtype=np.float32) + 0.5) / width
    yy, xx = np.meshgrid(ys, xs, indexing="ij")
    return xx.astype(np.float32), yy.astype(np.float32)


@dataclass
class Mask:
    """One mask component in normalised coordinates.

    ``params`` holds the geometry per ``kind``:

    * ``radial`` — ``cx, cy`` centre, ``rx, ry`` radii (all in ``[0, 1]``).
    * ``linear`` — ``x0, y0, x1, y1``: coverage ramps 0→1 from the first line to the
      second (a graduated filter).
    * ``brush``  — ``dabs``: a list of ``[x, y, radius, value]`` feathered circles.

    ``feather`` (0..1) softens the edge; ``invert`` flips coverage; ``subtract``
    removes this component from the combined coverage instead of adding to it.
    """

    kind: str
    params: dict[str, Any] = field(default_factory=dict)
    feather: float = 0.5
    invert: bool = False
    subtract: bool = False

    def coverage(self, height: int, width: int) -> Array:
        """Rasterise this mask to an ``(H, W)`` float coverage map in ``[0, 1]``."""
        if self.kind == "radial":
            cov = self._radial(height, width)
        elif self.kind == "linear":
            cov = self._linear(height, width)
        elif self.kind == "brush":
            cov = self._brush(height, width)
        else:  # unknown / not-yet-implemented kind → no coverage
            cov = np.zeros((height, width), dtype=np.float32)
        if self.invert:
            cov = 1.0 - cov
        return cov.astype(np.float32)

    def _radial(self, height: int, width: int) -> Array:
        xx, yy = _grid(height, width)
        cx = float(self.params.get("cx", 0.5))
        cy = float(self.params.get("cy", 0.5))
        rx = max(1e-4, float(self.params.get("rx", 0.3)))
        ry = max(1e-4, float(self.params.get("ry", 0.3)))
        dist = np.sqrt(((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2)
        feather = max(1e-3, float(self.feather))
        # 1 inside, ramping to 0 across the feather band ending at the edge (dist=1).
        return _smoothstep((1.0 - dist) / feather)

    def _linear(self, height: int, width: int) -> Array:
        xx, yy = _grid(height, width)
        x0 = float(self.params.get("x0", 0.0))
        y0 = float(self.params.get("y0", 0.0))
        x1 = float(self.params.get("x1", 1.0))
        y1 = float(self.params.get("y1", 0.0))
        dx, dy = x1 - x0, y1 - y0
        length2 = dx * dx + dy * dy
        if length2 < 1e-9:
            return np.zeros((height, width), dtype=np.float32)
        t = ((xx - x0) * dx + (yy - y0) * dy) / length2
        return _smoothstep(t)

    def _brush(self, height: int, width: int) -> Array:
        """Each dab touches only its bounding box — a stroke of hundreds of dabs
        stays cheap instead of costing a full-frame pass per dab."""
        cov = np.zeros((height, width), dtype=np.float32)
        feather = max(1e-3, float(self.feather))
        ys = (np.arange(height, dtype=np.float32) + 0.5) / height
        xs = (np.arange(width, dtype=np.float32) + 0.5) / width
        for dab in self.params.get("dabs", []):
            vals = list(dab)
            x, y, radius = float(vals[0]), float(vals[1]), max(1e-4, float(vals[2]))
            value = float(vals[3]) if len(vals) > 3 else 1.0
            # A dab's coverage is zero beyond dist = 1 (radius), i.e. `radius` away.
            x0 = max(0, int((x - radius) * width) - 1)
            x1 = min(width, int((x + radius) * width) + 2)
            y0 = max(0, int((y - radius) * height) - 1)
            y1 = min(height, int((y + radius) * height) + 2)
            if x0 >= x1 or y0 >= y1:
                continue
            dx = (xs[x0:x1] - x)[None, :]
            dy = (ys[y0:y1] - y)[:, None]
            dist = np.sqrt(dx * dx + dy * dy) / radius
            patch = value * _smoothstep((1.0 - dist) / feather)
            np.maximum(cov[y0:y1, x0:x1], patch, out=cov[y0:y1, x0:x1])
        return cov

    # -- serialisation ------------------------------------------------------ #

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "params": dict(self.params),
            "feather": self.feather,
            "invert": self.invert,
            "subtract": self.subtract,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Mask:
        return cls(
            kind=str(data.get("kind", "radial")),
            params=dict(data.get("params", {})),
            feather=float(data.get("feather", 0.5)),
            invert=bool(data.get("invert", False)),
            subtract=bool(data.get("subtract", False)),
        )

    def copy(self) -> Mask:
        return Mask.from_dict(self.to_dict())

    # -- convenience constructors (used by the Masks UI) -------------------- #

    @classmethod
    def radial(cls, cx: float = 0.5, cy: float = 0.5, size: float = 0.3) -> Mask:
        """A centred elliptical mask of the given normalised radius."""
        return cls("radial", {"cx": cx, "cy": cy, "rx": size, "ry": size}, feather=0.5)

    @classmethod
    def brush(cls) -> Mask:
        """An empty brush mask (dabs are painted on the canvas)."""
        return cls("brush", {"dabs": []}, feather=0.5)

    @classmethod
    def gradient(cls, axis: str = "vertical", start: float = 0.0, end: float = 0.4) -> Mask:
        """A graduated (linear) mask along ``vertical`` or ``horizontal`` from
        ``start`` (coverage 0) to ``end`` (coverage 1)."""
        if axis == "horizontal":
            params = {"x0": start, "y0": 0.5, "x1": end, "y1": 0.5}
        else:
            params = {"x0": 0.5, "y0": start, "x1": 0.5, "y1": end}
        return cls("linear", params, feather=0.5)


def blend_masked(baseline: Array, developed: Array, coverage: Array) -> Array:
    """Blend a layer's ``developed`` pixels over its ``baseline`` by ``coverage``.

    Both inputs must be in the same colour space (the layer's *identity* render and
    its *edited* render), so masking a RAW develop layer composites correctly in
    display space rather than mixing scene-linear and sRGB.
    """
    cov = coverage[..., None]
    out: Array = (baseline * (1.0 - cov) + developed * cov).astype(np.float32)
    return out


def combined_coverage(masks: list[Mask], height: int, width: int) -> Array | None:
    """Combine a layer's masks into one ``(H, W)`` coverage map, or ``None`` if none.

    Add components are unioned (max), then subtract components are removed, and the
    result is clamped to ``[0, 1]``. ``None`` means "no mask" — the layer applies
    globally, exactly as before masks existed.
    """
    if not masks:
        return None
    add = [m for m in masks if not m.subtract]
    sub = [m for m in masks if m.subtract]
    if not add:  # only subtractive masks make no sense alone → treat as global
        return None
    cov = np.zeros((height, width), dtype=np.float32)
    for mask in add:
        cov = np.maximum(cov, mask.coverage(height, width))
    for mask in sub:
        cov = cov * (1.0 - mask.coverage(height, width))
    return np.clip(cov, 0.0, 1.0).astype(np.float32)
