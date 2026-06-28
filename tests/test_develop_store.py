"""Tests for the per-photo develop edit store (layer stacks)."""

from __future__ import annotations

import json
from pathlib import Path

from vibephoto.core.paths import AppPaths
from vibephoto.processing.edit_state import EditState
from vibephoto.processing.layers import LayerStack
from vibephoto.processing.store import DevelopStore


def _store(tmp_path: Path) -> DevelopStore:
    return DevelopStore(AppPaths.under(tmp_path).ensure())


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    store = _store(tmp_path)
    stack = LayerStack.single(EditState(exposure=1.25, contrast=30))
    stack.add_layer("Layer 2")
    stack.active_state.vibrance = 40
    store.save(42, stack)
    assert store.load(42).to_dict() == stack.to_dict()


def test_missing_edit_loads_identity(tmp_path: Path) -> None:
    assert _store(tmp_path).load(999).is_identity()


def test_identity_edit_is_not_written(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save(7, LayerStack.single(EditState(exposure=1.0)))
    assert not store.load(7).is_identity()
    # Saving an identity stack removes the sidecar (no stale file lingers).
    store.save(7, LayerStack.single())
    assert store.load(7).is_identity()


def test_loads_legacy_single_state_save(tmp_path: Path) -> None:
    # A pre-layers save was a bare EditState dict; it must load as one layer.
    paths = AppPaths.under(tmp_path).ensure()
    (paths.develop_dir / "11.json").write_text(
        json.dumps(EditState(exposure=2.0).to_dict()), encoding="utf-8"
    )
    stack = DevelopStore(paths).load(11)
    assert len(stack.layers) == 1
    assert stack.active_state.exposure == 2.0


def test_corrupt_sidecar_degrades_to_identity(tmp_path: Path) -> None:
    paths = AppPaths.under(tmp_path).ensure()
    (paths.develop_dir / "5.json").write_text("{ not valid json", encoding="utf-8")
    assert DevelopStore(paths).load(5).is_identity()


def test_clear_removes_edit(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save(3, LayerStack.single(EditState(exposure=2.0)))
    store.clear(3)
    assert store.load(3).is_identity()
