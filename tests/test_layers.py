"""Tests for edit layers: the stack model, layered rendering, and history."""

from __future__ import annotations

import numpy as np

from vibephoto.processing.edit_state import EditState
from vibephoto.processing.geometry import Geometry, apply_geometry
from vibephoto.processing.history import EditHistory
from vibephoto.processing.image_buffer import ImageBuffer
from vibephoto.processing.layered_renderer import LayerRenderer, render_stack
from vibephoto.processing.layers import LayerStack


def _base() -> ImageBuffer:
    return ImageBuffer(np.full((20, 30, 3), 0.4, dtype=np.float32))


# -- stack model ---------------------------------------------------------- #


def test_single_stack_identity() -> None:
    assert LayerStack.single().is_identity()
    assert not LayerStack.single(EditState(exposure=1.0)).is_identity()


def test_add_and_remove_layers() -> None:
    stack = LayerStack.single()
    stack.add_layer("L2")
    assert len(stack.layers) == 2 and stack.active == 1
    stack.add_layer()
    assert stack.layers[2].name == "Layer 3" and stack.active == 2
    stack.remove_active()
    assert len(stack.layers) == 2 and stack.active == 1
    stack.remove_active()
    stack.remove_active()  # never removes the last layer
    assert len(stack.layers) == 1


def test_active_state_tracks_active_layer() -> None:
    stack = LayerStack.single(EditState(exposure=1.0))
    stack.add_layer()
    stack.active_state.contrast = 25
    assert stack.layers[1].state.contrast == 25
    stack.active = 0
    assert stack.active_state.exposure == 1.0


def test_serialization_roundtrip_and_backward_compat() -> None:
    stack = LayerStack.single(EditState(exposure=1.0))
    stack.add_layer("Top")
    stack.active_state.vibrance = 30
    stack.layers[1].enabled = False
    restored = LayerStack.from_dict(stack.to_dict())
    assert restored.to_dict() == stack.to_dict()
    assert restored.layers[1].name == "Top" and restored.layers[1].enabled is False

    legacy = LayerStack.from_dict(EditState(contrast=20).to_dict())  # pre-layers save
    assert len(legacy.layers) == 1 and legacy.active_state.contrast == 20


# -- layered rendering ---------------------------------------------------- #


def test_layers_compose() -> None:
    base = _base()
    stack = LayerStack.single(EditState(exposure=0.5))
    stack.add_layer()
    stack.active_state.exposure = 0.5
    two = render_stack(base, stack)
    one = render_stack(base, LayerStack.single(EditState(exposure=0.5)))
    assert float(two.data.mean()) > float(one.data.mean())  # two bumps = brighter


def test_disabled_layer_is_skipped() -> None:
    base = _base()
    stack = LayerStack.single(EditState(exposure=1.0))
    stack.add_layer()
    stack.active_state.exposure = 1.0
    stack.layers[1].enabled = False
    skipped = render_stack(base, stack)
    base_only = render_stack(base, LayerStack.single(EditState(exposure=1.0)))
    assert np.allclose(skipped.data, base_only.data)


def test_all_layers_off_linear_base_equals_identity_develop() -> None:
    # Disabling every layer on a RAW (scene-linear) base must show the *developed*
    # identity image (== Before), not the dark raw-linear pixels.
    linear = ImageBuffer(np.full((20, 30, 3), 0.18, dtype=np.float32), "linear")
    stack = LayerStack.single(EditState(exposure=1.0))
    stack.layers[0].enabled = False
    off = render_stack(linear, stack)
    before = render_stack(linear, LayerStack.single())  # identity develop
    assert off.colorspace == "srgb"
    assert np.allclose(off.data, before.data)
    assert not np.allclose(off.data, linear.data)  # not the raw-linear dump
    # The interactive renderer agrees with the one-shot path.
    assert np.allclose(LayerRenderer(linear).render(stack).data, before.data)


def test_all_layers_off_srgb_base_is_passthrough() -> None:
    # A display-referred (JPEG) base is already viewable: all-off = the original.
    srgb = ImageBuffer(np.full((8, 8, 3), 0.4, dtype=np.float32), "srgb")
    stack = LayerStack.single(EditState(exposure=1.0))
    stack.layers[0].enabled = False
    assert np.allclose(render_stack(srgb, stack).data, srgb.data)


def test_layer_renderer_matches_render_stack_after_edit() -> None:
    base = _base()
    stack = LayerStack.single(EditState(exposure=0.7))
    stack.add_layer()
    stack.active_state.contrast = 30
    renderer = LayerRenderer(base)
    assert np.allclose(renderer.render(stack).data, render_stack(base, stack).data)
    stack.active_state.contrast = 55  # edit the top layer, re-render
    assert np.allclose(renderer.render(stack).data, render_stack(base, stack).data)


# -- crop & straighten (photo-level geometry) ----------------------------- #


def test_geometry_identity_is_passthrough() -> None:
    base = _base()
    assert apply_geometry(base, Geometry()).data is base.data  # untouched


def test_geometry_crop_changes_dimensions_and_keeps_colorspace() -> None:
    linear = ImageBuffer(np.random.default_rng(0).random((40, 60, 3)).astype(np.float32), "linear")
    cropped = apply_geometry(linear, Geometry(left=0.25, top=0.0, right=0.75, bottom=1.0))
    assert cropped.width == 30 and cropped.height == 40  # half-width center crop
    assert cropped.colorspace == "linear"


def test_geometry_straighten_preserves_frame_size() -> None:
    base = _base()
    rotated = apply_geometry(base, Geometry(angle=5.0))
    assert (rotated.height, rotated.width) == (base.height, base.width)


def test_geometry_rotate90_swaps_dimensions() -> None:
    base = ImageBuffer(np.random.default_rng(0).random((20, 40, 3)).astype(np.float32), "srgb")
    turned = apply_geometry(base, Geometry(rotate90=1))
    assert (turned.height, turned.width) == (40, 20)  # 90° swaps W/H
    assert not Geometry(rotate90=1).is_identity()
    assert Geometry(rotate90=4).is_identity()  # full turn = no-op


def test_geometry_rotate90_survives_roundtrip() -> None:
    g = Geometry(rotate90=3, angle=2.0)
    assert Geometry.from_dict(g.to_dict()).rotate90 == 3


def test_render_stack_applies_crop_before_layers() -> None:
    base = ImageBuffer(np.full((20, 40, 3), 0.4, dtype=np.float32), "srgb")
    stack = LayerStack.single(EditState(exposure=0.0))
    stack.geometry = Geometry(left=0.0, top=0.0, right=0.5, bottom=1.0)
    out = render_stack(base, stack)
    assert out.width == 20 and out.height == 20  # cropped to the left half


def test_geometry_survives_stack_roundtrip() -> None:
    stack = LayerStack.single(EditState(exposure=1.0))
    stack.geometry = Geometry(left=0.1, top=0.2, right=0.9, bottom=0.8, angle=-3.5)
    restored = LayerStack.from_dict(stack.to_dict())
    assert restored.geometry.to_dict() == stack.geometry.to_dict()
    assert not stack.is_identity()  # a crop is a non-identity edit


def test_layer_renderer_recrops_when_geometry_changes() -> None:
    base = ImageBuffer(np.full((20, 40, 3), 0.4, dtype=np.float32), "srgb")
    renderer = LayerRenderer(base)
    stack = LayerStack.single()
    assert renderer.render(stack).width == 40  # full
    stack.geometry = Geometry(right=0.5)
    assert renderer.render(stack).width == 20  # re-cropped after geometry change


# -- history of stacks ---------------------------------------------------- #


def test_history_snapshots_whole_stack() -> None:
    stack = LayerStack.single()
    history: EditHistory[LayerStack] = EditHistory(stack)
    stack.active_state.exposure = 1.0
    history.push(stack)
    stack.add_layer()
    history.push(stack)
    previous = history.undo()
    assert len(previous.layers) == 1 and previous.active_state.exposure == 1.0
