"""Tests for the headless batch Auto-Edit helper."""

from __future__ import annotations

from pathlib import Path

from vibephoto.core.paths import AppPaths
from vibephoto.processing.batch import auto_edit_photo
from vibephoto.processing.loader import ImageLoader
from vibephoto.processing.store import DevelopStore
from vibephoto.raw.service import RawService


def test_auto_edit_photo_saves_non_identity_edit(make_jpeg, tmp_path: Path) -> None:
    src = make_jpeg(tmp_path / "shot.jpg", size=(400, 300), color=(40, 60, 30))
    store = DevelopStore(AppPaths.under(tmp_path / "app").ensure())
    loader = ImageLoader(RawService())

    ok = auto_edit_photo(loader, store, src, photo_id=7, is_raw=False)

    assert ok is True
    saved = store.load(7)
    assert not saved.is_identity()  # auto-tone produced a real edit
    assert len(saved.layers) == 1


def test_auto_hdr_kind_differs_from_edit(make_jpeg, tmp_path: Path) -> None:
    # The "hdr" kind applies the single-image HDR look, distinct from plain auto-tone.
    src = make_jpeg(tmp_path / "h.jpg", size=(400, 300), color=(50, 70, 40))
    store = DevelopStore(AppPaths.under(tmp_path / "app").ensure())
    loader = ImageLoader(RawService())
    auto_edit_photo(loader, store, src, 1, is_raw=False, kind="edit")
    edit_state = store.load(1).active_state.to_dict()
    auto_edit_photo(loader, store, src, 2, is_raw=False, kind="hdr")
    hdr_state = store.load(2).active_state.to_dict()
    assert edit_state != hdr_state  # HDR pushes shadows/highlights/clarity differently
    assert store.load(2).active_state.clarity > store.load(1).active_state.clarity


def test_apply_preset_same_layer_replaces(tmp_path: Path) -> None:
    from vibephoto.processing.batch import apply_preset_to_photo
    from vibephoto.processing.edit_state import EditState
    from vibephoto.processing.layers import LayerStack

    store = DevelopStore(AppPaths.under(tmp_path / "app").ensure())
    store.save(1, LayerStack.single(EditState(contrast=50)))  # existing edit
    apply_preset_to_photo(store, 1, "Warm", EditState(exposure=1.0), new_layer=False)
    stack = store.load(1)
    assert len(stack.layers) == 1  # same layer = replaced
    assert stack.active_state.exposure == 1.0 and stack.active_state.contrast == 0


def test_apply_preset_new_layer_stacks(tmp_path: Path) -> None:
    from vibephoto.processing.batch import apply_preset_to_photo
    from vibephoto.processing.edit_state import EditState
    from vibephoto.processing.layers import LayerStack

    store = DevelopStore(AppPaths.under(tmp_path / "app").ensure())
    store.save(1, LayerStack.single(EditState(contrast=50)))
    apply_preset_to_photo(store, 1, "Warm", EditState(exposure=1.0), new_layer=True)
    stack = store.load(1)
    assert len(stack.layers) == 2  # preset added on top
    assert stack.layers[0].state.contrast == 50  # existing edit kept underneath
    assert stack.layers[1].state.exposure == 1.0 and stack.layers[1].name == "Warm"


def test_auto_edit_photo_handles_missing_file(tmp_path: Path) -> None:
    store = DevelopStore(AppPaths.under(tmp_path / "app").ensure())
    loader = ImageLoader(RawService())
    assert auto_edit_photo(loader, store, tmp_path / "ghost.jpg", 1, is_raw=False) is False


def test_auto_edit_is_deterministic(make_jpeg, tmp_path: Path) -> None:
    # Same image → same auto edit, regardless of analysis size (resolution-independent).
    src = make_jpeg(tmp_path / "a.jpg", size=(600, 400), color=(90, 120, 70))
    store = DevelopStore(AppPaths.under(tmp_path / "app").ensure())
    loader = ImageLoader(RawService())
    auto_edit_photo(loader, store, src, 1, is_raw=False, long_edge=512)
    first = store.load(1).active_state.to_dict()
    auto_edit_photo(loader, store, src, 1, is_raw=False, long_edge=1024)
    second = store.load(1).active_state.to_dict()
    assert first["exposure"] == second["exposure"]
