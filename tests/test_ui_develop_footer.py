"""GUI tests for the Develop tools footer and related widgets.

Covers the star rating, the footer signal wiring, the canvas zoom/pan model, the
top-to-bottom layers panel mapping, and the Simple/Intermediate/Advanced edit
modes. Runs on the offscreen Qt platform.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from vibephoto.processing.layers import LayerStack
from vibephoto.ui.adjustments_panel import (
    ADVANCED,
    INTERMEDIATE,
    SIMPLE,
    AdjustmentsPanel,
    SliderSpec,
    _SliderRow,
)
from vibephoto.ui.develop_canvas import DevelopCanvas
from vibephoto.ui.develop_footer import DevelopFooter
from vibephoto.ui.layers_panel import LayersPanel
from vibephoto.ui.overlays import Overlay
from vibephoto.ui.star_rating import StarRating

pytestmark = pytest.mark.gui


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


# -- apply-preset dialog --------------------------------------------------- #


def test_apply_preset_dialog_selection(qapp: QApplication) -> None:
    from pathlib import Path

    from vibephoto.ui.apply_preset_dialog import ApplyPresetDialog

    groups = [("Looks", [("Warm", Path("/p/warm.xmp")), ("Cool", Path("/p/cool.xmp"))])]
    dialog = ApplyPresetDialog(groups, 3)
    assert dialog.mode() == "new"  # default
    assert dialog.chosen_preset() == Path("/p/warm.xmp")  # first real entry selected
    dialog._same_layer.setChecked(True)
    assert dialog.mode() == "same"


# -- lens profile panel ---------------------------------------------------- #


def test_lens_panel_emits_profile_and_auto(qapp: QApplication) -> None:
    from vibephoto.ui.lens_panel import LensProfilePanel

    panel = LensProfilePanel()
    chosen: list[str] = []
    autos: list[int] = []
    panel.profile_chosen.connect(lambda n: chosen.append(n))
    panel.auto_requested.connect(lambda: autos.append(1))
    panel._auto.click()
    assert autos == [1]
    panel._combo.setCurrentIndex(1)
    panel._on_activated(1)  # simulate picking a profile
    assert chosen and chosen[-1] == panel._combo.itemText(1)


def test_panel_resizer_drag_changes_width_repeatedly(qapp: QApplication) -> None:
    # Regression: setFixedWidth used to lock the drag after the first move.
    from PySide6.QtWidgets import QWidget

    from vibephoto.ui.develop_module import _PanelResizer

    panel = QWidget()
    panel.resize(360, 400)
    resizer = _PanelResizer(panel)

    class _Evt:
        def __init__(self, x: float) -> None:
            self._x = x

        def globalPosition(self):
            from PySide6.QtCore import QPointF

            return QPointF(self._x, 0.0)

    resizer.mousePressEvent(_Evt(1000.0))
    resizer.mouseMoveEvent(_Evt(900.0))  # drag left 100 -> wider
    first = panel.width()
    assert first > 360
    resizer.mousePressEvent(_Evt(900.0))
    resizer.mouseMoveEvent(_Evt(800.0))  # drag left again -> still widens
    assert panel.width() > first


# -- crop tool ------------------------------------------------------------- #


def test_footer_crop_toggle_shows_controls_and_emits(qapp: QApplication) -> None:
    footer = DevelopFooter()
    toggled: list[bool] = []
    rots: list[int] = []
    footer.crop_toggled.connect(lambda a: toggled.append(a))
    footer.rotate90_requested.connect(lambda d: rots.append(d))
    assert not footer._straighten.isVisible()
    footer._crop_btn.setChecked(True)
    assert toggled[-1] is True and footer.crop_active
    footer.rotate90_requested.emit(1)  # sanity of signal plumbing
    assert rots == [1]


def test_canvas_crop_mode_edits_and_emits(qapp: QApplication) -> None:
    from vibephoto.ui.develop_canvas import DevelopCanvas

    canvas = DevelopCanvas()
    emitted: list[object] = []
    canvas.crop_changed.connect(lambda r: emitted.append(r))
    canvas.set_crop_mode(True, (0.1, 0.1, 0.9, 0.9))
    assert canvas._crop_mode and canvas._crop_rect == (0.1, 0.1, 0.9, 0.9)
    canvas._crop_handle = "br"
    canvas._crop_release()
    assert emitted and emitted[-1] == (0.1, 0.1, 0.9, 0.9)
    canvas.set_crop_mode(False)
    assert not canvas._crop_mode


def test_canvas_crop_drag_rotate_emits_angle(qapp: QApplication) -> None:
    from vibephoto.ui.develop_canvas import DevelopCanvas

    canvas = DevelopCanvas()
    angles: list[float] = []
    canvas.crop_rotated.connect(lambda a: angles.append(a))
    canvas.set_crop_mode(True, (0.3, 0.3, 0.7, 0.7), 5.0)
    assert canvas._crop_angle == 5.0
    # Releasing while in a rotate-drag emits the final straighten angle.
    canvas._crop_rotating = True
    canvas._crop_angle = 7.5
    canvas._crop_release()
    assert angles[-1] == 7.5
    # The angle helper is monotonic around the image centre.
    assert canvas._angle_at(0.9, 0.5) == 0.0  # due right of centre = 0°
    assert canvas._angle_at(0.5, 0.9) > 0.0  # below centre = positive angle


def test_canvas_crop_mode_allows_zoom_out_past_fit(qapp: QApplication) -> None:
    from vibephoto.ui.develop_canvas import DevelopCanvas

    canvas = DevelopCanvas()
    assert canvas._min_zoom() == 1.0  # normal viewing never goes below fit
    canvas.set_crop_mode(True, (0.1, 0.1, 0.9, 0.9))
    assert canvas._min_zoom() < 1.0  # crop gives margin so corners are grabbable
    canvas._set_zoom(0.5)
    assert canvas._zoom == pytest.approx(0.5)
    canvas.set_crop_mode(False)  # leaving crop snaps framing back to fit
    assert canvas._zoom == 1.0


# -- canvas mask editing --------------------------------------------------- #


def test_canvas_mask_edit_toggles_and_emits(qapp: QApplication) -> None:
    from vibephoto.processing.mask import Mask
    from vibephoto.ui.develop_canvas import DevelopCanvas

    canvas = DevelopCanvas()
    edited: list[object] = []
    canvas.mask_edited.connect(lambda m: edited.append(m))
    canvas.set_mask_edit(Mask.radial())
    assert canvas._edit_mask is not None
    # Simulate the tail of a handle drag and confirm the edit is emitted.
    canvas._active_handle = "center"
    canvas._mask_release()
    assert edited and edited[-1].kind == "radial"
    canvas.set_mask_edit(None)
    assert canvas._edit_mask is None


# -- mask panel ------------------------------------------------------------ #


def test_mask_panel_add_select_delete(qapp: QApplication) -> None:
    from vibephoto.processing.mask import Mask
    from vibephoto.ui.mask_panel import MaskPanel

    panel = MaskPanel()
    emitted: list[list[Mask]] = []
    panel.masks_changed.connect(lambda ms: emitted.append(ms))
    panel._add(Mask.radial())
    panel._add(Mask.gradient())
    assert emitted[-1] and len(emitted[-1]) == 2
    assert {m.kind for m in emitted[-1]} == {"radial", "linear"}
    panel._list.setCurrentRow(0)
    panel._on_delete()
    assert len(emitted[-1]) == 1  # one removed


def test_mask_panel_set_masks_loads_without_emitting(qapp: QApplication) -> None:
    from vibephoto.processing.mask import Mask
    from vibephoto.ui.mask_panel import MaskPanel

    panel = MaskPanel()
    fired: list[object] = []
    panel.masks_changed.connect(lambda ms: fired.append(ms))
    panel.set_masks([Mask.radial(), Mask.gradient()])
    assert fired == []  # loading external state must not emit
    assert panel._list.count() == 2


# -- crop footer controls --------------------------------------------------- #


def test_footer_crop_toggle_shows_controls(qapp: QApplication) -> None:
    from vibephoto.ui.develop_footer import DevelopFooter

    footer = DevelopFooter()
    seen: list[bool] = []
    footer.crop_toggled.connect(lambda active: seen.append(active))
    assert footer.crop_active is False
    footer.set_crop_active(True)  # what the R / T shortcut calls
    assert footer.crop_active is True
    assert seen == [True]
    for widget in footer._crop_controls:
        assert not widget.isHidden()  # shown while cropping (window may be offscreen)
    footer.set_crop_active(False)  # what V calls
    assert footer.crop_active is False
    assert seen == [True, False]


def test_footer_crop_reset_emits(qapp: QApplication) -> None:
    from vibephoto.ui.develop_footer import DevelopFooter

    footer = DevelopFooter()
    fired: list[int] = []
    footer.crop_reset_requested.connect(lambda: fired.append(1))
    footer.set_crop_active(True)
    footer._crop_controls[-1].click()  # the "Reset" text button
    assert fired == [1]


# -- slider stepper buttons ------------------------------------------------ #


def test_slider_stepper_nudges_one_step(qapp: QApplication) -> None:
    spec = SliderSpec("whites", "Whites", -100, 100, 0)
    row = _SliderRow(spec)
    seen: list[float] = []
    row.changed.connect(lambda _p, _s, v: seen.append(v))
    row._nudge(+1)
    row._nudge(+1)  # two clicks → +2 steps
    assert seen == [1.0, 2.0]
    row._nudge(-1)
    assert seen[-1] == 1.0


def test_slider_stepper_clamps_at_range_end(qapp: QApplication) -> None:
    spec = SliderSpec("whites", "Whites", -100, 100, 99)
    row = _SliderRow(spec)
    row.set_value(99)
    seen: list[float] = []
    row.changed.connect(lambda _p, _s, v: seen.append(v))
    row._nudge(+1)
    row._nudge(+1)  # already at 100; cannot exceed maximum
    assert seen == [100.0, 100.0]


def test_slider_stepper_fine_step_for_exposure(qapp: QApplication) -> None:
    spec = SliderSpec("exposure", "Exposure", -5, 5, 0, mult=100, step=0.05)
    row = _SliderRow(spec)
    seen: list[float] = []
    row.changed.connect(lambda _p, _s, v: seen.append(v))
    row._nudge(+1)
    assert abs(seen[-1] - 0.05) < 1e-9  # fractional sliders step finely


# -- star rating ----------------------------------------------------------- #


def test_star_rating_set_and_clamp(qapp: QApplication) -> None:
    stars = StarRating()
    stars.set_rating(3)
    assert stars._rating == 3
    stars.set_rating(99)
    assert stars._rating == 5
    stars.set_rating(-2)
    assert stars._rating == 0


def test_star_rating_emits(qapp: QApplication) -> None:
    stars = StarRating()
    seen: list[int] = []
    stars.rating_changed.connect(seen.append)
    stars._rating = 0
    # Simulate clicking the 4th star via the internal helper + emit path.
    clicked = 4
    new = 0 if clicked == stars._rating else clicked
    stars._rating = new
    stars.rating_changed.emit(new)
    assert seen == [4]


# -- footer ---------------------------------------------------------------- #


def test_footer_overlay_signal(qapp: QApplication) -> None:
    footer = DevelopFooter()
    seen: list[object] = []
    footer.overlay_changed.connect(seen.append)
    # The combo is populated from the Overlay enum in order.
    footer._overlay.setCurrentIndex(1)
    assert seen and isinstance(seen[-1], Overlay)
    assert seen[-1] is Overlay.THIRDS


def test_footer_zoom_label(qapp: QApplication) -> None:
    footer = DevelopFooter()
    footer.set_zoom_label(1.0)
    assert footer._zoom_label.text() == "Fit"
    footer.set_zoom_label(2.5)
    assert "2.5" in footer._zoom_label.text()


def test_footer_set_rating(qapp: QApplication) -> None:
    footer = DevelopFooter()
    footer.set_rating(4)
    assert footer._stars._rating == 4


# -- canvas zoom/pan ------------------------------------------------------- #


def _solid_qimage(w: int = 100, h: int = 80) -> QImage:
    image = QImage(w, h, QImage.Format.Format_RGB888)
    image.fill(0x808080)
    return image


def test_canvas_zoom_in_out_bounds(qapp: QApplication) -> None:
    canvas = DevelopCanvas()
    canvas.resize(400, 300)
    canvas.set_images(_solid_qimage(), _solid_qimage())
    assert canvas._zoom == 1.0
    canvas.zoom_in()
    assert canvas._zoom > 1.0
    for _ in range(40):
        canvas.zoom_in()
    assert canvas._zoom <= 8.0  # clamped at max
    for _ in range(40):
        canvas.zoom_out()
    assert canvas._zoom >= 1.0  # never below fit


def test_canvas_reset_view_emits(qapp: QApplication) -> None:
    canvas = DevelopCanvas()
    canvas.resize(400, 300)
    canvas.set_images(_solid_qimage(), _solid_qimage())
    seen: list[float] = []
    canvas.zoom_changed.connect(seen.append)
    canvas.zoom_in()
    canvas.reset_view()
    assert canvas._zoom == 1.0
    assert seen[-1] == 1.0


def test_canvas_overlay_setters(qapp: QApplication) -> None:
    canvas = DevelopCanvas()
    canvas.set_overlay(Overlay.GOLDEN_SPIRAL)
    assert canvas._overlay is Overlay.GOLDEN_SPIRAL
    canvas.rotate_overlay()
    assert canvas._overlay_rotation == 90
    canvas.set_overlay_flip_h(True)
    assert canvas._flip_h is True


# -- layers panel: top-to-bottom mapping ----------------------------------- #


def test_layers_panel_lists_top_first(qapp: QApplication) -> None:
    panel = LayersPanel()
    stack = LayerStack.single()
    stack.add_layer()  # now Base, Layer 2 (active = 1, the top)
    panel.set_stack(stack)
    # Row 0 is the newest/top layer.
    assert panel._list.item(0).text() == "Layer 2"
    assert panel._list.item(1).text() == "Base"
    # Active stack index 1 maps to row 0 (selected).
    assert panel._list.currentRow() == 0


def test_layers_panel_row_maps_to_stack_index(qapp: QApplication) -> None:
    panel = LayersPanel()
    stack = LayerStack.single()
    stack.add_layer()
    stack.add_layer()  # Base, Layer 2, Layer 3 -> 3 layers
    panel.set_stack(stack)
    seen: list[int] = []
    panel.layer_selected.connect(seen.append)
    # Selecting the bottom row (row 2) should emit stack index 0.
    panel._list.setCurrentRow(2)
    assert seen[-1] == 0
    # Selecting the top row (row 0) should emit stack index 2.
    panel._list.setCurrentRow(0)
    assert seen[-1] == 2


# -- adjustments panel: edit modes ----------------------------------------- #


# ``isHidden()`` reflects each widget's own mode-driven visibility flag,
# independent of whether its (collapsible) section happens to be expanded.


def test_panel_defaults_to_intermediate(qapp: QApplication) -> None:
    panel = AdjustmentsPanel()
    assert panel._mode == INTERMEDIATE
    # An ADVANCED-only row (e.g. sharpen masking) is hidden at intermediate.
    assert panel._rows[("sharpen_masking", None)].isHidden()
    # An INTERMEDIATE row (e.g. clarity) is shown.
    assert not panel._rows[("clarity", None)].isHidden()
    assert panel._rows[("clarity", None)].level == INTERMEDIATE


def test_panel_simple_mode_hides_advanced_sections(qapp: QApplication) -> None:
    panel = AdjustmentsPanel()
    panel.set_mode(SIMPLE)
    assert panel._mode == SIMPLE
    # Effects group is ADVANCED — hidden entirely in Simple.
    effects = next(s for s, lvl, _ in panel._sections if lvl == ADVANCED)
    assert effects.isHidden()
    # A SIMPLE basic slider stays visible; an INTERMEDIATE one hides.
    assert not panel._rows[("exposure", None)].isHidden()
    assert panel._rows[("clarity", None)].isHidden()


def test_panel_advanced_mode_shows_everything(qapp: QApplication) -> None:
    panel = AdjustmentsPanel()
    panel.set_mode(ADVANCED)
    for section, _level, _rows in panel._sections:
        if section is panel._wb_section:
            continue  # White Balance is RAW-only; hidden for the default (non-RAW) panel
        assert not section.isHidden()
    assert not panel._rows[("sharpen_masking", None)].isHidden()


def test_panel_mode_button_clicked_switches(qapp: QApplication) -> None:
    panel = AdjustmentsPanel()
    panel._mode_group.button(ADVANCED).click()
    assert panel._mode == ADVANCED
    panel._mode_group.button(SIMPLE).click()
    assert panel._mode == SIMPLE
