"""The Develop module — the live, non-destructive editing surface.

Hosts the canvas, the adjustments panel, and the **layer stack** for the current
photo. The sliders edit the *active* layer; layers compose bottom-to-top (so you
can Auto-Edit one layer and drop a preset on another). Slider changes trigger a
debounced re-render (the :class:`LayerRenderer` recomputes only the active layer
and above) and a debounced save + undo step. Auto Edit/HDR, preset apply, and
Paste replace the active layer's settings; Copy/Paste move them between photos.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QImage, QKeyEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vibephoto.app.application import Application
from vibephoto.cache.previews import PreviewCache
from vibephoto.cache.thumbnails import ThumbnailCache
from vibephoto.catalog.models import Photo
from vibephoto.catalog.service import CatalogService
from vibephoto.presets.library import PresetLibrary
from vibephoto.processing.auto import auto_hdr, auto_tone
from vibephoto.processing.clipboard import SettingsClipboard
from vibephoto.processing.color import Array
from vibephoto.processing.edit_state import EditState
from vibephoto.processing.engine import DevelopEngine
from vibephoto.processing.geometry import Geometry, apply_geometry
from vibephoto.processing.history import EditHistory
from vibephoto.processing.image_buffer import ImageBuffer
from vibephoto.processing.layered_renderer import LayerRenderer
from vibephoto.processing.layers import LayerStack
from vibephoto.processing.lens_store import LensProfileStore
from vibephoto.processing.pipeline import PipelineRenderer
from vibephoto.processing.recent import LastEdit
from vibephoto.processing.resample import downscale_buffer
from vibephoto.processing.scene_linear import WB_REFERENCE_K, solve_white_balance
from vibephoto.processing.store import DevelopStore
from vibephoto.raw.service import RawService
from vibephoto.ui.adjustments_panel import AdjustmentsPanel
from vibephoto.ui.develop_canvas import DevelopCanvas, ndarray_to_qimage
from vibephoto.ui.develop_footer import DevelopFooter
from vibephoto.ui.module_views import ModuleId, ModuleView

logger = logging.getLogger(__name__)

_RENDER_DEBOUNCE_MS = 16  # ~60 fps draft-proxy cadence while dragging
_FULL_DEBOUNCE_MS = 130  # crisp full render lands soon after a drag (it's off-thread)
_SAVE_DEBOUNCE_MS = 600
_PREVIEW_EDGE = 480  # size of the hover-preview base (higher res, still fast)
_PROXY_EDGE = 768  # smart-preview proxy: small + fast so live dragging stays smooth

#: Fields Auto Edit / Auto HDR set (others — WB, HSL, curves, grade — are kept).
_AUTO_FIELDS = (
    "exposure", "contrast", "highlights", "shadows", "whites", "blacks",
    "clarity", "dehaze", "vibrance",
)


class DevelopModule(ModuleView):
    """Non-destructive editing surface: canvas + adjustments + layers."""

    module_id = ModuleId.DEVELOP

    #: Emitted when "Paste Settings" is Shift-clicked — the shell pastes to all selected.
    paste_to_selected_requested = Signal()
    #: True while a background full render is in flight (drives a status spinner).
    render_busy_changed = Signal(bool)
    #: Left/Right arrow pressed: navigate to the previous (-1) / next (+1) photo.
    #: The shell resolves the target from the filmstrip's current photo set.
    photo_nav_requested = Signal(int)

    def __init__(self, app: Application, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._app = app
        self._engine = app.resolve(DevelopEngine)
        self._store = app.resolve(DevelopStore)
        self._catalog = app.resolve(CatalogService)
        self._presets = app.resolve(PresetLibrary)
        self._clipboard = app.resolve(SettingsClipboard)
        self._last_edit = app.resolve(LastEdit)
        self._raw_service = app.resolve(RawService)
        self._previews = app.resolve(PreviewCache)
        self._thumbnails = app.resolve(ThumbnailCache)
        self._lens_store = LensProfileStore(app.paths.data_dir)

        self._photo: Photo | None = None
        self._renderer: LayerRenderer | None = None
        self._proxy_renderer: LayerRenderer | None = None  # smart-preview (low-res) renderer
        self._stack = LayerStack.single()
        self._history: EditHistory[LayerStack] = EditHistory(self._stack)
        self._before_qimage: QImage | None = None
        #: The unedited *developed* image (identity develop of the base). Auto Edit /
        #: Auto HDR analyse this fixed reference, so they stay idempotent — clicking
        #: again recomputes the same settings instead of compounding on the last edit.
        self._before_buffer: ImageBuffer | None = None
        self._preview_base: ImageBuffer | None = None
        #: Cached *unedited* low-res base for the crop tool, so straighten/rotate is a
        #: fast image rotate with no develop pipeline (just geometry).
        self._crop_base: ImageBuffer | None = None

        # Background work pool: photo decode + every full-resolution render run here,
        # never on the UI thread. One thread serialises the heavy jobs, so the
        # persistent full-res renderer's memoization cache is never touched
        # concurrently. Generation counters coalesce results: a stale render or a
        # stale photo load (superseded by a newer action) is dropped, not flashed in.
        self._render_pool = QThreadPool(self)
        self._render_pool.setMaxThreadCount(1)  # serialise heavy renders
        # Decodes get their own single thread: a photo load is never queued behind
        # (or dropped with) superseded render tasks, and vice versa.
        self._load_pool = QThreadPool(self)
        self._load_pool.setMaxThreadCount(1)
        # Prefetch (filmstrip neighbours) decodes on its own thread so warming the
        # smart-preview cache never delays the photo the user actually opened.
        self._prefetch_pool = QThreadPool(self)
        self._prefetch_pool.setMaxThreadCount(1)
        self._prefetching: set[str] = set()
        self._render_signals = _RenderSignals()
        self._render_signals.done.connect(self._on_full_rendered)
        self._render_signals.loaded.connect(self._on_photo_loaded)
        self._render_signals.before_ready.connect(self._on_before_ready)
        self._render_signals.prefetched.connect(self._on_prefetched)
        self._render_gen = 0
        self._load_gen = 0
        self._before_gen = 0
        self._render_busy = False

        # Smart previews: a fast low-res proxy renders live while editing, then the
        # crisp full-size preview lands once the edits settle (in the background).
        self._render_timer = _single_shot(self, _RENDER_DEBOUNCE_MS, self._render_preview)
        self._full_timer = _single_shot(self, _FULL_DEBOUNCE_MS, self._request_full_async)
        self._save_timer = _single_shot(self, _SAVE_DEBOUNCE_MS, self._persist)

        self._build_ui()

    # -- the active layer's edit state is what the sliders drive ------------ #

    @property
    def _state(self) -> EditState:
        return self._stack.active_layer.state

    @_state.setter
    def _state(self, value: EditState) -> None:
        self._stack.active_layer.state = value

    # -- construction ------------------------------------------------------- #

    def _build_ui(self) -> None:
        self._canvas = DevelopCanvas(self)
        self._panel = AdjustmentsPanel(self)
        self._panel.param_changed.connect(self._on_param_changed)
        self._panel.curve_changed.connect(self._on_curve_changed)
        self._panel.wb_picker_toggled.connect(self._canvas.set_pick_mode)
        self._panel.wb_auto_requested.connect(self._on_wb_auto)
        self._panel.wb_as_shot_requested.connect(self._on_wb_as_shot)
        self._canvas.point_picked.connect(self._on_wb_pick)
        self._panel.bw_toggled.connect(self._on_bw_toggled)
        self._panel.reset_requested.connect(self._on_reset)
        self._panel.preset_chosen.connect(self._on_preset_chosen)
        self._panel.add_preset_requested.connect(self._on_add_presets)
        self._panel.auto_edit_requested.connect(self._on_auto_edit)
        self._panel.auto_hdr_requested.connect(self._on_auto_hdr)
        self._panel.copy_requested.connect(self._on_copy_settings)
        self._panel.paste_requested.connect(self._on_paste_settings)
        self._panel.layer_selected.connect(self._on_layer_selected)
        self._panel.layer_added.connect(self._on_layer_added)
        self._panel.layer_removed.connect(self._on_layer_removed)
        self._panel.layer_toggled.connect(self._on_layer_toggled)
        self._panel.masks_changed.connect(self._on_masks_changed)
        self._panel.mask_panel.mask_selected.connect(self._canvas.set_mask_edit)
        self._canvas.mask_edited.connect(self._on_mask_edited)
        self._panel.profile_chosen.connect(self._on_profile_chosen)
        self._panel.lens_profile_chosen.connect(self._on_lens_profile)
        self._panel.lens_auto_requested.connect(self._on_lens_auto)
        self._panel.lens_profile_save_requested.connect(self._on_lens_save)
        self._panel.lens_profile_delete_requested.connect(self._on_lens_delete)
        self._panel.lens_panel.set_custom_profiles(self._lens_store.load())
        self._panel.preset_browser.set_render_callback(self._render_preset_preview)
        self._refresh_presets()

        # Tools footer: ratings, composition overlays, zoom, copy/paste, edit-like-last.
        self._footer = DevelopFooter(self)
        self._footer.rating_changed.connect(self._on_rating)
        self._footer.overlay_changed.connect(self._canvas.set_overlay)
        self._footer.overlay_opacity_changed.connect(self._canvas.set_overlay_opacity)
        self._footer.overlay_rotate_requested.connect(self._canvas.rotate_overlay)
        self._footer.overlay_flip_h_toggled.connect(self._canvas.set_overlay_flip_h)
        self._footer.overlay_flip_v_toggled.connect(self._canvas.set_overlay_flip_v)
        self._footer.zoom_in_requested.connect(self._canvas.zoom_in)
        self._footer.zoom_out_requested.connect(self._canvas.zoom_out)
        self._footer.copy_requested.connect(self._on_copy_settings)
        self._footer.paste_requested.connect(self._on_paste_settings)
        self._footer.edit_like_last_requested.connect(self._on_edit_like_last)
        self._footer.crop_toggled.connect(self._on_crop_toggled)
        self._footer.rotate90_requested.connect(self._on_rotate90)
        self._footer.straighten_changed.connect(self._on_straighten)
        self._footer.crop_reset_requested.connect(self._on_crop_reset)
        self._canvas.crop_changed.connect(self._on_crop_rect_changed)
        self._canvas.crop_rotated.connect(self._on_crop_rotated)
        self._canvas.zoom_changed.connect(self._footer.set_zoom_label)

        self._title = QLabel("No photo selected")
        self._title.setStyleSheet("color:#c9ccd1; padding:4px 8px; font-size:13px;")
        self._before_btn = QPushButton("Before/After (\\)")
        self._before_btn.setCheckable(True)
        self._before_btn.toggled.connect(self._canvas.set_show_before)

        top = QHBoxLayout()
        top.setContentsMargins(4, 2, 4, 2)
        top.addWidget(self._title, 1)
        top.addWidget(self._before_btn)

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(0)
        left.addLayout(top)
        left.addWidget(self._canvas, 1)
        left.addWidget(self._footer)
        left_widget = QWidget()
        left_widget.setLayout(left)

        # A thin draggable handle lets the user widen/narrow the adjustments panel
        # (a resizable UI). A QSplitter would be the obvious tool but it crashes on
        # teardown with this panel under PySide6, so a lightweight grip is used.
        self._panel_resizer = _PanelResizer(self._panel)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(left_widget, 1)
        root.addWidget(self._panel_resizer)
        root.addWidget(self._panel)

        self._add_shortcut(QKeySequence(Qt.Key.Key_Backslash), self._before_btn.toggle)
        # R or T enter the free crop tool; V returns to the mouse (pan / mask edit).
        self._add_shortcut(QKeySequence(Qt.Key.Key_R), lambda: self._set_crop(True))
        self._add_shortcut(QKeySequence(Qt.Key.Key_T), lambda: self._set_crop(True))
        self._add_shortcut(QKeySequence(Qt.Key.Key_V), lambda: self._set_crop(False))
        # F re-centres the view to fit-to-window (handy after scrolling out in crop).
        self._add_shortcut(QKeySequence(Qt.Key.Key_F), self._canvas.reset_view)
        self._add_shortcut(QKeySequence(QKeySequence.StandardKey.Undo), self._undo)
        self._add_shortcut(QKeySequence(QKeySequence.StandardKey.Redo), self._redo)
        self._add_shortcut(QKeySequence("Ctrl+Shift+Z"), self._redo)
        # 1-5 set the star rating, 0 clears it — same keys as the Library grid.
        for stars in range(6):

            def _rate(s: int = stars) -> None:
                self._rate_by_key(s)

            self._add_shortcut(QKeySequence(str(stars)), _rate)

    def _add_shortcut(self, sequence: QKeySequence, slot: Callable[[], object]) -> None:
        QShortcut(sequence, self).activated.connect(slot)

    # -- public API --------------------------------------------------------- #

    def load_photo(self, photo: Photo) -> None:
        """Open ``photo`` for editing, restoring its saved layer stack.

        The decode (LibRaw for RAW — seconds of work) and the first renders run on
        the background pool; the UI stays responsive and simply shows a loading
        title until :meth:`_on_photo_loaded` wires the results in. A newer
        ``load_photo`` bumps the load generation, so a stale decode is discarded.
        """
        if (
            self._renderer is not None
            and self._photo is not None
            and photo.id is not None
            and photo.id == self._photo.id
        ):
            return  # already editing this photo — keep the in-progress edit
        self.commit()  # persist edits to the previously-open photo first
        self._photo = photo
        path = self._catalog.resolve_path(photo)
        if path is None or not path.exists():
            self._set_unavailable(f"{photo.filename} — file offline")
            return

        # Pause editing while the decode is in flight; keep panels in sync with the
        # restored stack immediately so the UI doesn't show stale slider values.
        self._renderer = None
        self._proxy_renderer = None
        self._render_gen += 1
        self._before_gen += 1  # a stale Before from the previous photo must not land
        self._render_busy = False
        self._busy_changed()
        self._stack = self._store.load(photo.id) if photo.id is not None else LayerStack.single()
        self._history.reset(self._stack)
        self._canvas.set_pick_mode(False)
        self._canvas.set_mask_edit(None)
        self._panel.white_balance.set_picking(False)
        self._panel.set_raw_mode(photo.is_raw)  # Kelvin WB panel only for RAW
        self._sync_panel()
        self._footer.set_rating(photo.rating)
        self._title.setText(f"{photo.filename} — loading…")

        # Show *something* instantly: the grid thumbnail, blurry but immediate,
        # replaced the moment the decoded preview lands.
        self._show_placeholder(photo)

        self._load_gen += 1
        # Arrow-key browsing queues loads faster than decodes finish — drop any
        # still-queued stale load (and stale Before tasks; the generation bumps
        # above already invalidated them) so the newest photo starts immediately.
        self._load_pool.clear()
        task = _LoadTask(
            self._engine,
            self._raw_service,
            self._previews,
            path,
            photo,
            self._stack.geometry.copy(),
            self._load_gen,
            self._render_signals,
        )
        self._load_pool.start(task)

    def _show_placeholder(self, photo: Photo) -> None:
        """Put the photo's thumbnail on the canvas while the real decode runs."""
        if not photo.content_hash:
            return
        data = self._thumbnails.get_bytes(photo.content_hash)
        if not data:
            return
        image = QImage.fromData(data)
        if not image.isNull():
            self._canvas.set_images(image, image)

    def _on_photo_loaded(self, generation: int, payload: object) -> None:
        """A background photo decode finished — wire it in if it is still wanted."""
        if generation != self._load_gen or self._photo is None:
            return  # superseded by a newer load (or the module was cleared)
        if not isinstance(payload, _LoadedPhoto):
            self._set_unavailable(f"{self._photo.filename} — could not decode")
            return
        self._renderer = payload.renderer
        self._proxy_renderer = payload.proxy_renderer
        # "Before" is the unedited *develop* (identity edit) — for RAW that means the
        # tone-mapped scene-linear base, not the dark linear pixels themselves. The
        # buffer doubles as Auto Edit's stable original-state reference.
        self._before_buffer = payload.before_buffer
        self._before_qimage = payload.before_qimage
        self._preview_base = payload.preview_base
        self._panel.preset_browser.set_render_callback(self._render_preset_preview)
        # Calibrate the WB slider to this camera's true as-shot temperature.
        self._panel.white_balance.set_reference(payload.as_shot_kelvin or WB_REFERENCE_K)
        self._canvas.reset_view()
        self._title.setText(self._photo.filename)
        self._canvas.setFocus()  # so Left/Right photo navigation works immediately
        self._render_full()

    def commit(self) -> None:
        """Flush any pending edit to disk (called on app close / module switch)."""
        self._save_timer.stop()
        self._render_pool.clear()  # drop queued renders; the pool is reused next photo
        self._persist()
        if (
            self._photo is not None
            and self._photo.id is not None
            and self._renderer is not None
            and not self._stack.is_identity()
        ):
            self._last_edit.record(self._photo.id, self._stack)

    def refresh_from_store(self) -> None:
        """Reload the current photo's stack from disk (after an external paste)."""
        if self._photo is not None and self._photo.id is not None and self._renderer is not None:
            self._stack = self._store.load(self._photo.id)
            self._history.reset(self._stack)
            self._sync_panel()
            self._recompute_before()
            self._render_full()

    @property
    def current_photo(self) -> Photo | None:
        """The photo currently open for editing, if any."""
        return self._photo if self._renderer is not None else None

    def prefetch_photo(self, photo: Photo) -> None:
        """Warm the smart-preview cache for ``photo`` (a filmstrip neighbour).

        Decodes on the prefetch thread so the *next* arrow press opens from cache
        (~100 ms) instead of a full RAW decode. No-op for rendered files (they
        decode fast and are not cached) and for photos already cached/in flight.
        """
        key = photo.content_hash
        if not photo.is_raw or not key or key in self._prefetching:
            return
        if self._previews.contains(key):
            return
        path = self._catalog.resolve_path(photo)
        if path is None or not path.exists():
            return
        self._prefetching.add(key)
        task = _PrefetchTask(
            self._engine, self._raw_service, self._previews, path, photo, key,
            self._render_signals,
        )
        self._prefetch_pool.start(task)

    def _on_prefetched(self, key: str) -> None:
        self._prefetching.discard(key)

    @property
    def requested_photo(self) -> Photo | None:
        """The photo open — or still being decoded — in the editor.

        Unlike :attr:`current_photo` this is valid during an async load, so arrow
        navigation keeps its place while photos stream in.
        """
        return self._photo

    def keyPressEvent(self, event: QKeyEvent) -> None:
        # Enter/Return in the crop tool applies the crop (non-destructive — the
        # geometry is saved with the edit and export renders through it).
        if (
            event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and self._footer.crop_active
        ):
            self._set_crop(False)
            return
        # Left/Right navigate the filmstrip — but only when they reach the module
        # (a focused slider consumes arrows first, keeping keyboard nudge intact).
        if event.key() == Qt.Key.Key_Right:
            self.photo_nav_requested.emit(1)
        elif event.key() == Qt.Key.Key_Left:
            self.photo_nav_requested.emit(-1)
        else:
            super().keyPressEvent(event)

    # -- editing ------------------------------------------------------------ #

    def _on_param_changed(self, param: str, subkey: str | None, value: float) -> None:
        if self._renderer is None:
            return
        if subkey is None:
            setattr(self._state, param, value)
        else:
            getattr(self._state, param)[subkey] = value
        self._schedule_render()

    def _on_curve_changed(self, field: str, points: list[tuple[int, int]]) -> None:
        if self._renderer is None:
            return
        setattr(self._state, field, list(points))
        self._schedule_render()

    def _on_bw_toggled(self, enabled: bool) -> None:
        if self._renderer is None:
            return
        self._state.grayscale = enabled
        self._schedule_render()

    def _schedule_render(self) -> None:
        """Live edit: fast proxy now, crisp full render once edits settle, then save."""
        self._render_timer.start()
        self._full_timer.start()
        self._save_timer.start()

    # -- white balance ------------------------------------------------------ #

    def _on_wb_pick(self, nx: float, ny: float) -> None:
        """Eyedropper: make the sampled pixel neutral by solving Temp/Tint for it."""
        if self._renderer is None:
            return
        kelvin, tint = solve_white_balance(self._sample_base(nx, ny))
        self._panel.white_balance.set_picking(False)
        self._set_white_balance(kelvin, tint)

    def _on_wb_auto(self) -> None:
        """Auto WB: assume the whole frame averages to neutral (grey world)."""
        if self._renderer is None:
            return
        mean = self._renderer.base.data.reshape(-1, 3).mean(axis=0)
        kelvin, tint = solve_white_balance(mean)
        self._set_white_balance(kelvin, tint)

    def _on_wb_as_shot(self) -> None:
        self._set_white_balance(WB_REFERENCE_K, 0.0)

    def _set_white_balance(self, kelvin: float, tint: float) -> None:
        if self._renderer is None:
            return
        self._state.wb_kelvin = float(kelvin)
        self._state.wb_tint = float(tint)
        self._panel.set_state(self._state)
        self._render_full()
        self._persist()

    def _sample_base(self, nx: float, ny: float, radius: int = 3) -> Array:
        """Average the scene-linear base over a small window at a normalized point."""
        assert self._renderer is not None
        data = self._renderer.base.data
        height, width = data.shape[0], data.shape[1]
        x = min(width - 1, max(0, round(nx * (width - 1))))
        y = min(height - 1, max(0, round(ny * (height - 1))))
        region = data[max(0, y - radius): y + radius + 1, max(0, x - radius): x + radius + 1]
        sample: Array = region.reshape(-1, 3).mean(axis=0).astype(np.float32)
        return sample

    def _on_reset(self) -> None:
        if self._renderer is not None:
            self._apply_state(EditState())

    def _on_preset_chosen(self, name: str, state: object) -> None:
        if self._renderer is None or not isinstance(state, EditState):
            return
        self._apply_state(state.copy())
        self._title.setText(f"{self._photo.filename if self._photo else ''} — {name}")

    def _on_add_presets(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Add Preset Folder")
        if not folder:
            return
        count = self._presets.import_folder(Path(folder))
        self._refresh_presets()
        QMessageBox.information(self, "Presets", f"Imported {count} preset(s) into your library.")

    def _on_auto_edit(self) -> None:
        if self._renderer is not None and self._before_buffer is not None:
            self._apply_state(self._merged(auto_tone(self._before_buffer)))

    def _on_auto_hdr(self) -> None:
        if self._renderer is not None and self._before_buffer is not None:
            self._apply_state(self._merged(auto_hdr(self._before_buffer)))

    def _on_copy_settings(self) -> None:
        if self._renderer is not None:
            self._clipboard.copy(self._state)
            self._title.setText(f"{self._photo.filename if self._photo else ''} — settings copied")

    def _on_paste_settings(self) -> None:
        pasted = self._clipboard.paste()
        if pasted is None:
            QMessageBox.information(self, "Paste Settings", "Copy settings from a photo first.")
            return
        shift = bool(
            QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier
        )
        if shift:
            self.paste_to_selected_requested.emit()
        elif self._renderer is not None:
            self._apply_state(pasted)

    def _on_rating(self, rating: int) -> None:
        if self._photo is not None and self._photo.id is not None:
            self._catalog.photos.set_rating(self._photo.id, rating)
            self._photo.rating = rating

    def _rate_by_key(self, rating: int) -> None:
        """Keyboard rating (0-5): update the footer stars and persist."""
        if self._photo is None:
            return
        self._footer.set_rating(rating)  # set_rating does not re-emit — no double save
        self._on_rating(rating)

    def _on_edit_like_last(self) -> None:
        if self._renderer is None:
            return
        stack = self._last_edit.stack
        same_photo = self._photo is not None and self._last_edit.photo_id == self._photo.id
        if stack is None or same_photo:
            QMessageBox.information(
                self, "Edit Like Last", "Edit a different photo first, then come back."
            )
            return
        self._stack = stack
        self._sync_panel()
        self._recompute_before()
        self._render_full()
        self._persist()

    # -- layers ------------------------------------------------------------- #

    def _on_layer_added(self) -> None:
        if self._renderer is None:
            return
        self._stack.add_layer()
        self._sync_panel()
        self._render_full()
        self._persist()

    def _on_layer_removed(self) -> None:
        if self._renderer is None or len(self._stack.layers) <= 1:
            return
        self._stack.remove_active()
        self._sync_panel()
        self._render_full()
        self._persist()

    def _on_layer_selected(self, row: int) -> None:
        if self._renderer is None or not 0 <= row < len(self._stack.layers):
            return
        self._stack.active = row
        self._panel.set_state(self._state)  # sliders follow the active layer
        self._panel.mask_panel.set_masks(self._stack.active_layer.masks)
        self._save_timer.start()

    def _on_layer_toggled(self, row: int, enabled: bool) -> None:
        if self._renderer is None or not 0 <= row < len(self._stack.layers):
            return
        self._stack.layers[row].enabled = enabled
        self._render_full()
        self._save_timer.start()

    def _on_masks_changed(self, masks: object) -> None:
        """Update the active layer's local-adjustment masks and re-render."""
        if self._renderer is None or not isinstance(masks, list):
            return
        self._stack.active_layer.masks = masks
        self._canvas.set_mask_edit(self._panel.mask_panel.selected_mask())  # keep overlay synced
        self._render_full()
        self._persist()

    def _on_mask_edited(self, mask: object) -> None:
        """A canvas handle-drag / brush stroke updated the selected mask."""
        from vibephoto.processing.mask import Mask

        if self._renderer is None or not isinstance(mask, Mask):
            return
        index = self._panel.mask_panel.current_index()
        masks = self._stack.active_layer.masks
        if not 0 <= index < len(masks):
            return
        masks[index] = mask
        self._panel.mask_panel.update_current(mask)  # sync the panel sliders
        self._render_preview()  # fast draft while dragging; full lands on settle
        self._full_timer.start()
        self._save_timer.start()

    # -- crop tool ---------------------------------------------------------- #

    def _set_crop(self, active: bool) -> None:
        """Drive the crop tool from a keyboard shortcut (R/T enter, V exits)."""
        if self._renderer is None and active:
            return
        self._footer.set_crop_active(active)  # flips the footer toggle → _on_crop_toggled

    def _on_crop_reset(self) -> None:
        """Reset the crop to the full frame (handles, straighten, 90° rotation)."""
        if self._renderer is None:
            return
        self._stack.geometry = Geometry()
        self._footer.set_straighten(0.0)
        self._canvas.set_crop_mode(self._footer.crop_active, (0.0, 0.0, 1.0, 1.0), 0.0)
        if self._footer.crop_active:
            self._render_crop_view()
        else:
            self._recompute_before()
            self._render_full()
        self._persist()

    def _on_crop_toggled(self, active: bool) -> None:
        """Enter/leave the on-canvas crop tool."""
        if self._renderer is None:
            return
        if active:
            g = self._stack.geometry
            self._canvas.set_mask_edit(None)  # crop and mask editing are exclusive
            # Cache the *edited* image (small, full frame, no geometry) once: the
            # crop is placed over what the photo actually looks like, and
            # straighten/rotate is then just a fast image rotate.
            self._crop_base = self._render_uncropped_proxy()
            self._footer.set_straighten(g.angle)
            self._canvas.set_crop_mode(True, (g.left, g.top, g.right, g.bottom), g.angle)
            self._render_crop_view()
        else:
            self._crop_base = None
            self._canvas.set_crop_mode(False)
            self._recompute_before()  # the crop changed the framing
            self._sync_panel()
            self._render_full()
            self._persist()

    def _render_uncropped_proxy(self) -> ImageBuffer | None:
        """A proxy-sized *edited* render of the full (un-cropped, un-rotated) frame.

        A throwaway draft renderer over an identity-geometry copy of the stack, so
        the crop tool shows the photo with its adjustments applied — not the
        unedited original — without disturbing the live renderers' caches.
        """
        if self._renderer is None:
            return None
        base = downscale_buffer(self._renderer.base, _PROXY_EDGE)
        stack = self._stack.copy()
        stack.geometry = Geometry()  # full frame — the overlay draws the crop rect
        return LayerRenderer(base, draft=True).render(stack)

    def _render_crop_view(self) -> None:
        """Show the *uncropped* but rotated/straightened original (fast: just geometry)."""
        if self._crop_base is None:
            return
        g = self._stack.geometry
        rotated = apply_geometry(self._crop_base, Geometry(angle=g.angle, rotate90=g.rotate90))
        image = ndarray_to_qimage(rotated.to_uint8())
        self._canvas.set_images(image, image)

    def _on_crop_rotated(self, angle: float) -> None:
        """Drag-to-rotate (outside the crop box) updated the straighten angle."""
        if self._renderer is None:
            return
        self._stack.geometry.angle = float(angle)
        self._footer.set_straighten(angle)
        self._render_crop_view()
        self._save_timer.start()

    def _on_crop_rect_changed(self, rect: object) -> None:
        if self._renderer is None or not isinstance(rect, tuple) or len(rect) != 4:
            return
        g = self._stack.geometry
        g.left, g.top, g.right, g.bottom = (float(v) for v in rect)
        self._save_timer.start()  # overlay already shows it; just persist

    def _on_straighten(self, degrees: float) -> None:
        if self._renderer is None:
            return
        self._stack.geometry.angle = float(degrees)
        if self._footer.crop_active:
            self._render_crop_view()
        self._save_timer.start()

    def _on_rotate90(self, direction: int) -> None:
        if self._renderer is None:
            return
        g = self._stack.geometry
        g.rotate90 = (g.rotate90 + int(direction)) % 4
        g.left, g.top, g.right, g.bottom = 0.0, 0.0, 1.0, 1.0  # reset crop to the new frame
        self._canvas.set_crop_mode(self._footer.crop_active, (0.0, 0.0, 1.0, 1.0), g.angle)
        if self._footer.crop_active:
            self._render_crop_view()
        else:
            self._recompute_before()
            self._render_full()
        self._persist()

    def _on_profile_chosen(self, name: str) -> None:
        """Set the active layer's creative/camera base look."""
        if self._renderer is None:
            return
        self._state.profile = name
        self._render_full()
        self._persist()

    def _apply_lens_profile(self, name: str) -> None:
        """Apply a built-in / custom lens profile (Manual = leave the sliders alone)."""
        from vibephoto.processing.lens import LENS_PROFILES, MANUAL_PROFILE

        if self._renderer is None:
            return
        if name == MANUAL_PROFILE:
            self._panel.lens_panel.set_profile_name(name)  # tune the sliders by hand
            return
        values = LENS_PROFILES.get(name) or self._lens_store.load().get(name)
        if values is None:
            return
        self._state.lens_distortion, self._state.lens_ca, self._state.lens_vignetting = values
        self._panel.set_state(self._state)  # refresh the Distortion/Defringe/Vignetting sliders
        self._panel.lens_panel.set_profile_name(name)
        self._render_full()
        self._persist()

    def _on_lens_save(self, name: str) -> None:
        """Save the current lens amounts as a reusable custom profile."""
        if self._renderer is None:
            return
        values = (self._state.lens_distortion, self._state.lens_ca, self._state.lens_vignetting)
        self._lens_store.save(name, values)
        self._panel.lens_panel.set_custom_profiles(self._lens_store.load())
        self._panel.lens_panel.set_profile_name(name)

    def _on_lens_delete(self, name: str) -> None:
        self._lens_store.delete(name)
        self._panel.lens_panel.set_custom_profiles(self._lens_store.load())

    def _on_lens_profile(self, name: str) -> None:
        self._apply_lens_profile(name)

    def _on_lens_auto(self) -> None:
        """Detect the lens from the photo's EXIF and apply the matching correction."""
        from vibephoto.processing.lens import AUTO_LENS_PROFILE, detect_lens_profile

        if self._renderer is None or self._photo is None:
            return
        meta = (
            self._catalog.photos.get_metadata(self._photo.id)
            if self._photo.id is not None
            else None
        )
        key = (
            detect_lens_profile(meta.lens, meta.focal_length, meta.camera_model)
            if meta is not None
            else None
        )
        lens_name = (meta.lens if meta else None) or "unknown lens"
        if key is None:
            key = AUTO_LENS_PROFILE  # no lens metadata — assume the common fisheye case
            detail = "no lens info → fisheye"
        elif key == "None":
            detail = f"{lens_name} — no correction needed"
        else:
            detail = f"{lens_name} → {key}"
        self._apply_lens_profile(key)
        self._title.setText(f"{self._photo.filename} — Lens: {detail}")

    def _undo(self) -> None:
        if self._renderer is not None and self._history.can_undo:
            self._restore(self._history.undo())

    def _redo(self) -> None:
        if self._renderer is not None and self._history.can_redo:
            self._restore(self._history.redo())

    # -- helpers ------------------------------------------------------------ #

    def _merged(self, auto: EditState) -> EditState:
        """Copy only the auto-controlled tone fields onto the active layer's edit."""
        state = self._state.copy()
        for field in _AUTO_FIELDS:
            setattr(state, field, getattr(auto, field))
        return state

    def _apply_state(self, state: EditState) -> None:
        """Set the active layer's state from a discrete action and record it."""
        self._state = state
        self._panel.set_state(self._state)
        self._render_full()
        self._persist()

    def _restore(self, stack: LayerStack) -> None:
        """Restore a whole stack from undo/redo without pushing a new step."""
        self._stack = stack
        self._sync_panel()
        self._recompute_before()  # geometry may have changed with the undo step
        self._render_full()
        if self._photo is not None and self._photo.id is not None:
            self._store.save(self._photo.id, self._stack)

    def _recompute_before(self) -> None:
        """Rebuild the Before reference (identity develop of the geometry-applied base).

        Runs on the load pool (never cleared, unlike the render queue): a ~300 ms
        full-size identity develop would otherwise stall the UI on every undo, crop
        exit, or 90° rotate. Until the new frame lands, the previous Before stays —
        a brief, visual-only staleness. A generation counter drops superseded runs.
        """
        if self._renderer is None:
            return
        self._before_gen += 1
        task = _BeforeTask(
            self._renderer.base,
            self._stack.geometry.copy(),
            self._before_gen,
            self._render_signals,
        )
        self._load_pool.start(task)

    def _on_before_ready(self, generation: int, buffer: object, qimage: object) -> None:
        if generation != self._before_gen:
            return  # superseded by a newer geometry change
        if isinstance(buffer, ImageBuffer) and isinstance(qimage, QImage):
            self._before_buffer = buffer
            self._before_qimage = qimage
            self._canvas.set_before(qimage)  # refresh if the Before view is showing

    def _sync_panel(self) -> None:
        self._panel.set_state(self._state)
        self._panel.set_layers(self._stack)
        self._panel.mask_panel.set_masks(self._stack.active_layer.masks)

    def _render_full(self) -> None:
        """Show the current edit: instant proxy feedback + a crisp render off-thread.

        Nothing full-resolution ever runs on the UI thread for large photos — the
        proxy gives immediate feedback and the full frame lands from the pool. Small
        photos (no proxy) render synchronously; at that size the full render *is*
        real-time, and skipping the pool keeps the renderer single-threaded.
        """
        if self._renderer is None or self._before_qimage is None:
            return
        if self._proxy_renderer is None:
            self._render_sync_small()
            return
        self._render_preview()
        self._request_full_async()

    def _render_sync_small(self) -> None:
        """Full render on the UI thread — only for small (proxy-less) photos.

        This is the *only* place the full-res renderer runs on the UI thread, and it
        happens only when no proxy exists — in which case no pool render tasks are
        ever created, so the renderer's memoization cache stays single-threaded.
        """
        if self._renderer is None or self._before_qimage is None:
            return
        self._render_timer.stop()
        self._full_timer.stop()
        self._render_gen += 1  # supersede any in-flight background render
        pixels = self._renderer.render(self._stack).to_uint8()
        self._canvas.set_images(ndarray_to_qimage(pixels), self._before_qimage)
        self._panel.update_histogram(pixels)

    # -- background full render (smooth live editing) ----------------------- #

    def _request_full_async(self) -> None:
        """Render the current edit at full quality on a pool thread (coalesced).

        The live proxy already shows the edit; this lands the crisp full-resolution
        frame without blocking the UI. The persistent :class:`LayerRenderer` keeps
        its per-stage memoization across renders, so a settled slider drag
        recomputes only the stages downstream of the change even at full size. A
        newer edit bumps the generation, so a render that finishes late is ignored.
        """
        if self._renderer is None or self._before_qimage is None:
            return
        if self._proxy_renderer is None:
            self._render_sync_small()
            return
        self._render_timer.stop()
        self._render_gen += 1
        self._render_busy = True
        self._busy_changed()
        self._render_pool.clear()  # drop superseded *queued* tasks (running one finishes)
        task = _FullRenderTask(
            self._renderer, self._stack.copy(), self._render_gen, self._render_signals
        )
        self._render_pool.start(task)

    def _on_full_rendered(self, generation: int, qimage: object, pixels: object) -> None:
        """A background full render finished — apply it if it is still the latest."""
        if generation != self._render_gen:
            return  # superseded by a newer edit
        self._render_busy = False
        self._busy_changed()
        if self._before_qimage is not None and isinstance(qimage, QImage):
            self._canvas.set_images(qimage, self._before_qimage)
            if isinstance(pixels, np.ndarray):
                self._panel.update_histogram(pixels)

    def _busy_changed(self) -> None:
        """Notify listeners (e.g. a status spinner) whether a render is in flight."""
        self.render_busy_changed.emit(self._render_busy)

    def _render_preview(self) -> None:
        """Render the fast low-res proxy for live feedback while editing."""
        if self._proxy_renderer is None:
            self._render_sync_small()  # small images skip the proxy — full is already fast
            return
        if self._before_qimage is None:
            return
        buffer = self._proxy_renderer.render(self._stack)
        self._canvas.set_images(ndarray_to_qimage(buffer.to_uint8()), self._before_qimage)

    def _render_preset_preview(self, state: EditState) -> QImage:
        base = self._preview_base
        if base is None:
            return QImage()
        return ndarray_to_qimage(PipelineRenderer(base).render(state).to_uint8())

    def _persist(self) -> None:
        if self._photo is not None and self._photo.id is not None and self._renderer is not None:
            self._history.push(self._stack)
            self._store.save(self._photo.id, self._stack)

    def _refresh_presets(self) -> None:
        self._panel.preset_browser.set_groups(self._presets.list_groups())

    def _set_unavailable(self, message: str) -> None:
        self._render_gen += 1  # invalidate in-flight renders
        self._load_gen += 1  # and any in-flight photo load
        self._before_gen += 1  # and any in-flight Before recompute
        self._render_pool.clear()
        self._render_busy = False
        self._renderer = None
        self._proxy_renderer = None
        self._preview_base = None
        self._before_buffer = None
        self._crop_base = None
        self._canvas.set_mask_edit(None)
        self._canvas.clear()
        self._panel.clear_histogram()
        self._title.setText(message)


class _RenderSignals(QObject):
    """Carries finished background work back to the UI thread."""

    done = Signal(int, object, object)  # (generation, QImage, uint8 pixels)
    loaded = Signal(int, object)  # (load generation, _LoadedPhoto | None)
    before_ready = Signal(int, object, object)  # (before generation, ImageBuffer, QImage)
    prefetched = Signal(str)  # cache key of a finished neighbour prefetch


class _FullRenderTask(QRunnable):
    """Renders the full-quality frame off the UI thread (NumPy drops the GIL).

    Uses the module's *persistent* full-res renderer so per-stage memoization
    survives across renders — but only ever from the single-threaded pool, and with
    a private copy of the stack, so no mutable state is shared with the UI. The
    ``generation`` lets the UI ignore results superseded by a newer edit.
    """

    def __init__(
        self, renderer: LayerRenderer, stack: LayerStack, generation: int, signals: _RenderSignals
    ) -> None:
        super().__init__()
        self._renderer = renderer
        self._stack = stack
        self._generation = generation
        self._signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            buffer = self._renderer.render(self._stack)
            pixels = buffer.to_uint8()
            self._signals.done.emit(self._generation, ndarray_to_qimage(pixels), pixels)
        except Exception:
            logger.exception("Background render failed")
            self._signals.done.emit(self._generation, None, None)  # clears the busy state


class _BeforeTask(QRunnable):
    """Recomputes the Before reference (geometry + identity develop) off-thread.

    Runs on the (never-cleared) load pool so it cannot be dropped by the render
    queue's coalescing; reads only the immutable base and a private geometry copy.
    """

    def __init__(
        self,
        base: ImageBuffer,
        geometry: Geometry,
        generation: int,
        signals: _RenderSignals,
    ) -> None:
        super().__init__()
        self._base = base
        self._geometry = geometry
        self._generation = generation
        self._signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            geo_base = apply_geometry(self._base, self._geometry)
            before = PipelineRenderer(geo_base).render(EditState())
            self._signals.before_ready.emit(
                self._generation, before, ndarray_to_qimage(before.to_uint8())
            )
        except Exception:
            logger.exception("Before-reference render failed")


class _LoadedPhoto:
    """Everything a photo needs to start editing, computed off the UI thread."""

    __slots__ = (
        "as_shot_kelvin",
        "before_buffer",
        "before_qimage",
        "preview_base",
        "proxy_renderer",
        "renderer",
    )

    def __init__(
        self,
        renderer: LayerRenderer,
        proxy_renderer: LayerRenderer | None,
        before_buffer: ImageBuffer,
        before_qimage: QImage,
        preview_base: ImageBuffer,
        as_shot_kelvin: float | None,
    ) -> None:
        self.renderer = renderer
        self.proxy_renderer = proxy_renderer
        self.before_buffer = before_buffer
        self.before_qimage = before_qimage
        self.preview_base = preview_base
        self.as_shot_kelvin = as_shot_kelvin


def _decode_base(
    engine: DevelopEngine,
    raw_service: RawService,
    previews: PreviewCache,
    path: Path,
    photo: Photo,
) -> tuple[ImageBuffer, float | None] | None:
    """The photo's preview-sized base + as-shot Kelvin, via the smart-preview cache.

    A cache hit skips the multi-second LibRaw decode (and the second RAW open for
    the as-shot temperature). RAW misses are decoded and written back; rendered
    files (JPEG/PNG/TIFF) decode fast enough that caching them isn't worth the disk.
    """
    key = photo.content_hash if photo.is_raw else None
    if key:
        cached = previews.load(key)
        if cached is not None:
            return cached
    renderer = engine.open_layered(path, is_raw=photo.is_raw)
    if renderer is None:
        return None
    as_shot = raw_service.as_shot_temperature(path) if photo.is_raw else None
    if key:
        previews.save(key, renderer.base, as_shot)
    return (renderer.base, as_shot)


class _LoadTask(QRunnable):
    """Decodes a photo and prepares its renderers/reference images off-thread.

    RAW decode takes seconds; doing it here (plus the identity "Before" render and
    the proxy/preview downscales) keeps photo switching stutter-free. The
    smart-preview cache turns repeat opens into ~100 ms loads. Emits ``loaded``
    with a :class:`_LoadedPhoto`, or ``None`` when the decode failed.
    """

    def __init__(
        self,
        engine: DevelopEngine,
        raw_service: RawService,
        previews: PreviewCache,
        path: Path,
        photo: Photo,
        geometry: Geometry,
        generation: int,
        signals: _RenderSignals,
    ) -> None:
        super().__init__()
        self._engine = engine
        self._raw_service = raw_service
        self._previews = previews
        self._path = path
        self._photo = photo
        self._geometry = geometry
        self._generation = generation
        self._signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            decoded = _decode_base(
                self._engine, self._raw_service, self._previews, self._path, self._photo
            )
            if decoded is None:
                self._signals.loaded.emit(self._generation, None)
                return
            base, as_shot = decoded
            renderer = LayerRenderer(base)
            proxy = _make_proxy(base, _PROXY_EDGE)
            geo_base = apply_geometry(base, self._geometry)
            before = PipelineRenderer(geo_base).render(EditState())
            payload = _LoadedPhoto(
                renderer=renderer,
                proxy_renderer=proxy,
                before_buffer=before,
                before_qimage=ndarray_to_qimage(before.to_uint8()),
                preview_base=downscale_buffer(base, _PREVIEW_EDGE),
                as_shot_kelvin=as_shot,
            )
            self._signals.loaded.emit(self._generation, payload)
        except Exception:
            logger.exception("Background photo load failed")
            self._signals.loaded.emit(self._generation, None)


class _PrefetchTask(QRunnable):
    """Warms the smart-preview cache for a filmstrip neighbour, off-thread.

    Runs on its own single-thread pool so it never delays the photo the user
    actually opened; emits ``prefetched`` (with the cache key) when done so the
    module can clear its in-flight marker.
    """

    def __init__(
        self,
        engine: DevelopEngine,
        raw_service: RawService,
        previews: PreviewCache,
        path: Path,
        photo: Photo,
        key: str,
        signals: _RenderSignals,
    ) -> None:
        super().__init__()
        self._engine = engine
        self._raw_service = raw_service
        self._previews = previews
        self._path = path
        self._photo = photo
        self._key = key
        self._signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            _decode_base(self._engine, self._raw_service, self._previews, self._path, self._photo)
        except Exception:
            logger.exception("Preview prefetch failed for %s", self._path)
        finally:
            self._signals.prefetched.emit(self._key)


class _PanelResizer(QWidget):
    """A vertical grip that resizes the adjustments panel by dragging.

    Gives a resizable UI without a QSplitter (which segfaults on teardown with the
    develop panel). The clamp uses fixed bounds — not the panel's min/max, because
    ``setFixedWidth`` collapses those to the current width and would lock the drag.
    """

    _WIDTH = 9
    _MIN_PANEL = 350
    _MAX_PANEL = 760

    def __init__(self, panel: QWidget) -> None:
        super().__init__()
        self._panel = panel
        self._drag_x = 0.0
        self._start_width = 0
        self._hover = False
        self.setFixedWidth(self._WIDTH)
        self.setCursor(Qt.CursorShape.SplitHCursor)
        self.setToolTip("Drag to resize the panel")

    def enterEvent(self, _event: object) -> None:
        self._hover = True
        self.update()

    def leaveEvent(self, _event: object) -> None:
        self._hover = False
        self.update()

    def mousePressEvent(self, event: object) -> None:
        self._drag_x = event.globalPosition().x()  # type: ignore[attr-defined]
        self._start_width = self._panel.width()

    def mouseMoveEvent(self, event: object) -> None:
        delta = self._drag_x - event.globalPosition().x()  # type: ignore[attr-defined] # left = wider
        target = int(min(self._MAX_PANEL, max(self._MIN_PANEL, self._start_width + delta)))
        self._panel.setFixedWidth(target)

    def paintEvent(self, _event: object) -> None:
        from PySide6.QtGui import QColor, QPainter

        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#3d8bfd" if self._hover else "#2f3338"))
        # Three dots down the middle to signal a draggable grip.
        painter.setPen(QColor("#e6e8eb" if self._hover else "#8a8d93"))
        cx = self.width() // 2
        cy = self.height() // 2
        for dy in (-8, 0, 8):
            painter.drawEllipse(cx - 1, cy + dy - 1, 2, 2)


def _single_shot(parent: QWidget, interval_ms: int, slot: object) -> QTimer:
    timer = QTimer(parent)
    timer.setSingleShot(True)
    timer.setInterval(interval_ms)
    timer.timeout.connect(slot)
    return timer


def _make_proxy(base: ImageBuffer, long_edge: int) -> LayerRenderer | None:
    """A low-res *draft* renderer for live editing, or ``None`` when the base is small.

    Draft mode skips the blur-heavy presence/detail/effects stages, so dragging any
    slider stays smooth; the full-quality frame lands from ``_render_full`` once the
    edit settles.
    """
    if max(base.width, base.height) <= long_edge:
        return None  # already small enough to render full-size in real time
    return LayerRenderer(downscale_buffer(base, long_edge), draft=True)
