"""Tests for local-adjustment masks: coverage rasterisation + masked compositing."""

from __future__ import annotations

import numpy as np

from vibephoto.processing.edit_state import EditState
from vibephoto.processing.image_buffer import ImageBuffer
from vibephoto.processing.layered_renderer import render_stack
from vibephoto.processing.layers import EditLayer, LayerStack
from vibephoto.processing.mask import Mask, blend_masked, combined_coverage

# -- coverage rasterisation ----------------------------------------------- #


def test_radial_coverage_peaks_at_centre() -> None:
    cov = Mask("radial", {"cx": 0.5, "cy": 0.5, "rx": 0.3, "ry": 0.3}).coverage(50, 50)
    assert cov[25, 25] > 0.9  # centre fully inside
    assert cov[0, 0] < 0.05  # corner outside
    assert cov.shape == (50, 50)


def test_radial_invert_flips_coverage() -> None:
    params = {"cx": 0.5, "cy": 0.5, "rx": 0.3, "ry": 0.3}
    normal = Mask("radial", params).coverage(40, 40)
    inverted = Mask("radial", params, invert=True).coverage(40, 40)
    assert np.allclose(normal + inverted, 1.0, atol=1e-5)


def test_linear_coverage_ramps_across_axis() -> None:
    cov = Mask("linear", {"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 0.0}).coverage(10, 100)
    row = cov[5]
    assert row[0] < 0.1 and row[-1] > 0.9  # 0 at left, 1 at right
    assert np.all(np.diff(row) >= -1e-6)  # monotonic increasing


def test_brush_dabs_paint_local_coverage() -> None:
    mask = Mask("brush", {"dabs": [[0.25, 0.25, 0.1, 1.0]]}, feather=0.5)
    cov = mask.coverage(100, 100)
    assert cov[25, 25] > 0.8  # under the dab
    assert cov[75, 75] < 0.05  # far away


def test_combined_coverage_add_and_subtract() -> None:
    add = Mask("radial", {"cx": 0.5, "cy": 0.5, "rx": 0.5, "ry": 0.5})
    sub = Mask("radial", {"cx": 0.5, "cy": 0.5, "rx": 0.2, "ry": 0.2}, subtract=True)
    cov = combined_coverage([add, sub], 60, 60)
    assert cov is not None
    assert cov[30, 30] < 0.1  # centre carved out by the subtract mask
    assert cov[30, 12] > 0.4  # mid-ring still covered
    assert combined_coverage([], 8, 8) is None  # no masks = global (None)


def test_mask_constructors() -> None:
    r = Mask.radial(0.4, 0.6, 0.2)
    assert r.kind == "radial" and r.params["cx"] == 0.4 and r.params["rx"] == 0.2
    v = Mask.gradient("vertical", 0.0, 0.5)
    assert v.kind == "linear" and v.params["y0"] == 0.0 and v.params["y1"] == 0.5
    h = Mask.gradient("horizontal", 0.1, 0.9)
    assert h.params["x0"] == 0.1 and h.params["y0"] == h.params["y1"]


def test_blend_masked_interpolates() -> None:
    base = np.zeros((4, 4, 3), dtype=np.float32)
    dev = np.ones((4, 4, 3), dtype=np.float32)
    cov = np.full((4, 4), 0.25, dtype=np.float32)
    out = blend_masked(base, dev, cov)
    assert np.allclose(out, 0.25)


# -- masked compositing through the renderer ------------------------------ #


def test_masked_layer_applies_only_inside_mask() -> None:
    base = ImageBuffer(np.full((40, 40, 3), 0.4, dtype=np.float32), "srgb")
    stack = LayerStack(
        [
            EditLayer(
                "Local",
                EditState(exposure=2.0),  # strong brighten
                masks=[Mask("radial", {"cx": 0.5, "cy": 0.5, "rx": 0.25, "ry": 0.25})],
            )
        ]
    )
    out = render_stack(base, stack)
    centre = float(out.data[20, 20].mean())
    corner = float(out.data[0, 0].mean())
    assert centre > corner + 0.1  # brightened in the masked centre only
    assert abs(corner - 0.4) < 1e-3  # outside the mask = untouched base


def test_global_layer_unchanged_by_empty_masks() -> None:
    base = ImageBuffer(np.full((8, 8, 3), 0.4, dtype=np.float32), "srgb")
    masked = render_stack(base, LayerStack([EditLayer("L", EditState(exposure=1.0), masks=[])]))
    plain = render_stack(base, LayerStack.single(EditState(exposure=1.0)))
    assert np.allclose(masked.data, plain.data)  # no masks == global edit


def test_layer_masks_survive_roundtrip() -> None:
    layer = EditLayer(
        "L",
        EditState(exposure=1.0),
        masks=[Mask("brush", {"dabs": [[0.1, 0.2, 0.05, 1.0]]}, feather=0.3, subtract=True)],
    )
    stack = LayerStack([layer])
    restored = LayerStack.from_dict(stack.to_dict())
    assert restored.to_dict() == stack.to_dict()
    assert restored.layers[0].masks[0].kind == "brush"
    assert restored.layers[0].masks[0].subtract is True
