"""GUI smoke tests for the Develop module (offscreen Qt)."""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from vibephoto.app.bootstrap import build_application
from vibephoto.catalog.indexer import IndexerService
from vibephoto.catalog.service import CatalogService
from vibephoto.core.config import AppSettings
from vibephoto.core.paths import AppPaths
from vibephoto.processing.edit_state import EditState
from vibephoto.ui.develop_module import DevelopModule
from vibephoto.ui.module_views import LibraryModule

pytestmark = pytest.mark.gui


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def app_with_photo(tmp_path, make_jpeg):
    paths = AppPaths.under(tmp_path / "app").ensure()
    settings = AppSettings()
    settings.catalog.backup_on_launch = False
    settings.ui.restore_workspace = False
    application = build_application(paths=paths, settings=settings, configure_logs=False)
    application.start()
    pics = tmp_path / "pics"
    make_jpeg(pics / "shot.jpg", size=(900, 600), color=(110, 130, 90))
    application.resolve(IndexerService).index_folder(pics)
    yield application
    application.stop()


def _first_photo(app):
    return app.resolve(CatalogService).photos.list_all()[0]


def _load(qapp: QApplication, module: DevelopModule, photo) -> None:
    """Open ``photo`` and pump events until the background decode lands."""
    import time

    module.load_photo(photo)
    deadline = time.monotonic() + 10.0
    while module._renderer is None and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.005)
    assert module._renderer is not None, "photo load did not complete"


def test_develop_opens_photo_and_renders(qapp: QApplication, app_with_photo) -> None:
    module = DevelopModule(app_with_photo)
    _load(qapp, module, _first_photo(app_with_photo))
    assert module._renderer is not None
    assert not module._canvas._after.isNull()  # a real preview was produced


def test_slider_change_updates_state_and_rerenders(qapp: QApplication, app_with_photo) -> None:
    module = DevelopModule(app_with_photo)
    _load(qapp, module, _first_photo(app_with_photo))
    module._on_param_changed("exposure", None, 2.0)
    module._render_full()
    assert module._state.exposure == 2.0
    assert not module._canvas._after.isNull()


def test_background_full_render_delivers_and_signals_busy(qapp: QApplication, app_with_big_photo):
    # Needs a photo big enough to get a proxy — small photos render synchronously
    # and never dispatch to the pool.
    module = DevelopModule(app_with_big_photo)
    _load(qapp, module, _first_photo(app_with_big_photo))
    busy_states: list[bool] = []
    module.render_busy_changed.connect(lambda b: busy_states.append(b))

    module._on_param_changed("exposure", None, 1.5)
    module._request_full_async()  # dispatch a background full render
    assert module._render_busy is True
    assert busy_states and busy_states[-1] is True

    # Stop the debounce timers so no *additional* render is dispatched while we
    # wait — we only want to observe this one completing.
    module._render_timer.stop()
    module._full_timer.stop()
    import time

    deadline = time.monotonic() + 10.0
    while module._render_busy and time.monotonic() < deadline:
        module._render_pool.waitForDone(100)
        qapp.processEvents()  # pump the queued result back to the UI thread
    assert module._render_busy is False  # finished
    assert busy_states[-1] is False  # spinner told to stop
    assert not module._canvas._after.isNull()


def test_failed_background_render_emits_without_crashing(qapp: QApplication) -> None:
    from vibephoto.processing.layers import LayerStack
    from vibephoto.ui import develop_module as dm

    class _BoomRenderer:
        def render(self, _stack):
            raise ValueError("boom")

    signals = dm._RenderSignals()
    seen: list[tuple] = []
    signals.done.connect(lambda g, img, px: seen.append((g, img, px)))
    dm._FullRenderTask(_BoomRenderer(), LayerStack.single(), 5, signals).run()  # must not raise
    assert seen == [(5, None, None)]  # emitted a clearing result instead of crashing


def test_auto_edit_is_idempotent(qapp: QApplication, app_with_photo) -> None:
    # Clicking Auto Edit twice must converge: the second click recomputes the same
    # settings from the original developed image, not compound on the first edit.
    module = DevelopModule(app_with_photo)
    _load(qapp, module, _first_photo(app_with_photo))
    module._on_auto_edit()
    fields = ("exposure", "contrast", "whites", "blacks", "highlights", "shadows")
    first = {f: getattr(module._state, f) for f in fields}
    module._on_auto_edit()
    second = {f: getattr(module._state, f) for f in fields}
    assert first == second  # idempotent — no drift on repeated Auto Edit


def test_bw_toggle_sets_grayscale(qapp: QApplication, app_with_photo) -> None:
    module = DevelopModule(app_with_photo)
    _load(qapp, module, _first_photo(app_with_photo))
    module._on_bw_toggled(True)
    module._render_full()
    assert module._state.grayscale is True


def test_edits_persist_across_reopen(qapp: QApplication, app_with_photo) -> None:
    photo = _first_photo(app_with_photo)
    module = DevelopModule(app_with_photo)
    _load(qapp, module, photo)
    module._on_param_changed("contrast", None, 35.0)
    module.commit()  # flush to the develop store

    reopened = DevelopModule(app_with_photo)
    _load(qapp, reopened, photo)
    assert reopened._state.contrast == 35.0


def test_reset_restores_identity(qapp: QApplication, app_with_photo) -> None:
    module = DevelopModule(app_with_photo)
    _load(qapp, module, _first_photo(app_with_photo))
    module._on_param_changed("exposure", None, 1.0)
    module._on_reset()
    assert module._state.is_identity()


def test_undo_redo_walks_edit_history(qapp: QApplication, app_with_photo) -> None:
    module = DevelopModule(app_with_photo)
    _load(qapp, module, _first_photo(app_with_photo))
    module._on_param_changed("exposure", None, 2.0)
    module._persist()  # records a history step (normally the debounced save does this)
    module._on_param_changed("exposure", None, -1.0)
    module._persist()

    module._undo()
    assert module._state.exposure == 2.0
    module._undo()
    assert module._state.exposure == 0.0
    module._redo()
    assert module._state.exposure == 2.0


def test_arrow_keys_request_photo_navigation(qapp: QApplication, app_with_photo) -> None:
    # Left/Right reaching the module emit photo_nav_requested(-1 / +1); other keys don't.
    from PySide6.QtCore import QEvent
    from PySide6.QtCore import Qt as QtCore_Qt
    from PySide6.QtGui import QKeyEvent

    module = DevelopModule(app_with_photo)
    _load(qapp, module, _first_photo(app_with_photo))
    seen: list[int] = []
    module.photo_nav_requested.connect(seen.append)
    for key in (QtCore_Qt.Key.Key_Right, QtCore_Qt.Key.Key_Left, QtCore_Qt.Key.Key_A):
        module.keyPressEvent(
            QKeyEvent(QEvent.Type.KeyPress, key, QtCore_Qt.KeyboardModifier.NoModifier)
        )
    assert seen == [1, -1]


def test_requested_photo_tracks_in_flight_load(qapp: QApplication, app_with_photo) -> None:
    # requested_photo is valid even mid-decode, so navigation keeps its place.
    module = DevelopModule(app_with_photo)
    photo = _first_photo(app_with_photo)
    module.load_photo(photo)  # async — renderer not ready yet
    assert module.requested_photo is not None
    assert module.requested_photo.id == photo.id
    _load(qapp, module, photo)  # settle before teardown


def test_rating_keys_set_and_clear(qapp: QApplication, app_with_photo) -> None:
    # 1-5 rate the open photo from the keyboard; 0 clears. Persisted to the catalog.
    module = DevelopModule(app_with_photo)
    _load(qapp, module, _first_photo(app_with_photo))
    module._rate_by_key(4)
    assert module._photo is not None and module._photo.rating == 4
    assert _first_photo(app_with_photo).rating == 4  # persisted
    module._rate_by_key(0)
    assert module._photo.rating == 0
    assert _first_photo(app_with_photo).rating == 0


def test_preset_chosen_applies_state(qapp: QApplication, app_with_photo) -> None:
    module = DevelopModule(app_with_photo)
    _load(qapp, module, _first_photo(app_with_photo))
    module._on_preset_chosen("Test Look", EditState(contrast=40, vibrance=20))
    assert module._state.contrast == 40
    assert not module._canvas._after.isNull()


def test_preset_hover_render_callback_produces_image(qapp: QApplication, app_with_photo) -> None:
    module = DevelopModule(app_with_photo)
    _load(qapp, module, _first_photo(app_with_photo))
    image = module._render_preset_preview(EditState(exposure=1.0))
    assert not image.isNull()


def test_apply_imported_preset_renders(qapp: QApplication, app_with_photo) -> None:
    module = DevelopModule(app_with_photo)
    _load(qapp, module, _first_photo(app_with_photo))
    module._state = EditState(temp=40, contrast=30, vibrance=25, grade_shadow_hue=220,
                              grade_shadow_sat=20)
    module._render_full()
    assert not module._canvas._after.isNull()


def test_crop_view_shows_edited_photo(qapp: QApplication, app_with_photo) -> None:
    # Entering the crop tool must show the photo WITH its adjustments, not the
    # unedited original.
    module = DevelopModule(app_with_photo)
    _load(qapp, module, _first_photo(app_with_photo))
    module._on_param_changed("exposure", None, 2.0)
    module._footer.set_crop_active(True)  # -> _on_crop_toggled(True)
    assert module._crop_base is not None
    assert module._before_buffer is not None
    edited_mean = float(module._crop_base.data.mean())
    original_mean = float(module._before_buffer.data.mean())
    assert edited_mean > original_mean + 0.05  # +2 EV clearly visible
    module._footer.set_crop_active(False)


def test_library_reset_edits_restores_original(qapp: QApplication, app_with_photo) -> None:
    from vibephoto.processing.layers import LayerStack
    from vibephoto.processing.store import DevelopStore

    library = LibraryModule(app_with_photo)
    library.reload()
    photo = _first_photo(app_with_photo)
    store = app_with_photo.resolve(DevelopStore)
    store.save(photo.id, LayerStack.single(EditState(contrast=40.0)))
    assert not store.load(photo.id).is_identity()

    pasted: list[object] = []
    library.settings_pasted.connect(lambda: pasted.append(True))
    library._reset_edits([photo])
    assert store.load(photo.id).is_identity()  # back to the original
    assert pasted  # Develop is told to refresh


def test_min_rating_filter_emits_and_syncs_buttons(qapp: QApplication, app_with_photo) -> None:
    # The filmstrip's mini filter mirrors the Library's; the signal + button sync
    # is what keeps the two bars consistent.
    library = LibraryModule(app_with_photo)
    library.reload()
    seen: list[int] = []
    library.min_rating_changed.connect(seen.append)
    library.set_min_rating(3)
    assert seen == [3]
    assert library._rating_filter.checkedId() == 3
    library.set_min_rating(0)
    assert seen == [3, 0]
    assert library._rating_filter.checkedId() == 0


def test_library_double_click_emits_and_selects(qapp: QApplication, app_with_photo) -> None:
    library = LibraryModule(app_with_photo)
    library.reload()
    captured: list[object] = []
    library.photo_activated.connect(captured.append)
    library._on_double_click(library._model.index(0, 0))
    assert captured and getattr(captured[0], "filename", None) == "shot.jpg"

    library._grid.setCurrentIndex(library._model.index(0, 0))
    selected = library.selected_photo()
    assert selected is not None and selected.filename == "shot.jpg"


# -- layers + auto + copy/paste ------------------------------------------- #


def test_layers_compose_auto_then_preset(qapp: QApplication, app_with_photo) -> None:
    module = DevelopModule(app_with_photo)
    _load(qapp, module, _first_photo(app_with_photo))
    module._on_param_changed("exposure", None, 1.0)  # edit the base layer

    module._on_layer_added()  # new layer, becomes active
    assert len(module._stack.layers) == 2 and module._stack.active == 1
    module._on_preset_chosen("Look", EditState(contrast=40))
    assert module._stack.layers[1].state.contrast == 40
    assert module._stack.layers[0].state.exposure == 1.0  # base layer preserved

    module._on_layer_selected(0)  # sliders follow the active layer
    assert module._state.exposure == 1.0
    module._on_layer_toggled(1, False)
    assert module._stack.layers[1].enabled is False
    assert not module._canvas._after.isNull()


def test_auto_edit_sets_tone(qapp: QApplication, app_with_photo) -> None:
    module = DevelopModule(app_with_photo)
    _load(qapp, module, _first_photo(app_with_photo))
    module._on_auto_edit()
    state = module._state
    assert any(getattr(state, f) != 0 for f in ("exposure", "whites", "blacks", "contrast"))


def test_copy_paste_settings_roundtrip(qapp: QApplication, app_with_photo) -> None:
    module = DevelopModule(app_with_photo)
    _load(qapp, module, _first_photo(app_with_photo))
    module._on_param_changed("contrast", None, 33.0)
    module._on_copy_settings()
    module._on_reset()
    assert module._state.contrast == 0
    module._on_paste_settings()  # no Shift held -> paste onto the current photo
    assert module._state.contrast == 33


# -- smart previews + graph edits ----------------------------------------- #


def test_make_proxy_skips_small_images(qapp: QApplication) -> None:
    # A small base needs no proxy (full render is already fast); a large one does.
    import numpy as np

    from vibephoto.processing.image_buffer import ImageBuffer
    from vibephoto.ui.develop_module import _PROXY_EDGE, _make_proxy

    small = ImageBuffer(np.zeros((400, 400, 3), dtype=np.float32), "srgb")
    big = ImageBuffer(np.zeros((1200, 1600, 3), dtype=np.float32), "srgb")
    assert _make_proxy(small, _PROXY_EDGE) is None
    assert _make_proxy(big, _PROXY_EDGE) is not None


@pytest.fixture
def app_with_big_photo(tmp_path, make_jpeg):
    paths = AppPaths.under(tmp_path / "big").ensure()
    settings = AppSettings()
    settings.catalog.backup_on_launch = False
    settings.ui.restore_workspace = False
    application = build_application(paths=paths, settings=settings, configure_logs=False)
    application.start()
    pics = tmp_path / "pics"
    make_jpeg(pics / "big.jpg", size=(2400, 1600), color=(120, 110, 100))
    application.resolve(IndexerService).index_folder(pics)
    yield application
    application.stop()


def test_big_image_builds_smaller_proxy(qapp: QApplication, app_with_big_photo) -> None:
    module = DevelopModule(app_with_big_photo)
    _load(qapp, module, _first_photo(app_with_big_photo))
    assert module._proxy_renderer is not None
    assert module._renderer is not None
    proxy_base = module._proxy_renderer.base
    full_base = module._renderer.base
    assert max(proxy_base.width, proxy_base.height) <= 1024
    assert max(proxy_base.width, proxy_base.height) < max(full_base.width, full_base.height)
    # The live proxy render produces a frame on the canvas.
    module._on_param_changed("exposure", None, 1.5)
    module._render_preview()
    assert not module._canvas._after.isNull()


def test_curve_change_updates_state_and_renders(qapp: QApplication, app_with_photo) -> None:
    module = DevelopModule(app_with_photo)
    _load(qapp, module, _first_photo(app_with_photo))
    module._on_curve_changed("curve_rgb", [(0, 0), (128, 180), (255, 255)])
    module._render_full()
    assert module._state.curve_rgb == [(0, 0), (128, 180), (255, 255)]
    assert not module._canvas._after.isNull()


def test_grade_param_change_routes_through_param_changed(qapp, app_with_photo) -> None:
    module = DevelopModule(app_with_photo)
    _load(qapp, module, _first_photo(app_with_photo))
    # The grade wheels emit grade_* via the panel's param_changed signal.
    module._panel.grade_panel.param_changed.emit("grade_shadow_hue", None, 210.0)
    module._panel.grade_panel.param_changed.emit("grade_shadow_sat", None, 40.0)
    assert module._state.grade_shadow_hue == 210.0
    assert module._state.grade_shadow_sat == 40.0


# -- white balance workflow ----------------------------------------------- #


def test_wb_as_shot_resets_to_reference(qapp: QApplication, app_with_photo) -> None:
    from vibephoto.processing.scene_linear import WB_REFERENCE_K

    module = DevelopModule(app_with_photo)
    _load(qapp, module, _first_photo(app_with_photo))
    module._on_param_changed("wb_kelvin", None, 3200.0)
    assert module._state.wb_kelvin == 3200.0
    module._on_wb_as_shot()
    assert module._state.wb_kelvin == WB_REFERENCE_K
    assert module._state.wb_tint == 0.0


def test_wb_auto_sets_a_white_balance(qapp: QApplication, app_with_photo) -> None:
    module = DevelopModule(app_with_photo)
    _load(qapp, module, _first_photo(app_with_photo))
    module._on_wb_auto()  # grey-world over the base
    assert 2000.0 <= module._state.wb_kelvin <= 50000.0


def test_wb_pick_samples_and_sets(qapp: QApplication, app_with_photo) -> None:
    module = DevelopModule(app_with_photo)
    _load(qapp, module, _first_photo(app_with_photo))
    module._panel.white_balance._picker.setChecked(True)
    module._on_wb_pick(0.5, 0.5)  # canvas would emit this on a click while picking
    assert 2000.0 <= module._state.wb_kelvin <= 50000.0
    assert not module._panel.white_balance._picker.isChecked()  # picker disarms


def test_wb_picker_toggles_canvas_pick_mode(qapp: QApplication, app_with_photo) -> None:
    module = DevelopModule(app_with_photo)
    _load(qapp, module, _first_photo(app_with_photo))
    module._panel.wb_picker_toggled.emit(True)
    assert module._canvas._picking is True
    module._panel.wb_picker_toggled.emit(False)
    assert module._canvas._picking is False
