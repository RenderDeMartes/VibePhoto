"""GUI tests for the interactive graph widgets — tone curve + colour wheels."""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtWidgets import QApplication

from vibephoto.processing.edit_state import EditState
from vibephoto.ui.color_wheels import ColorGradingPanel, ColorWheel, _hsv_to_rgb
from vibephoto.ui.curve_editor import ToneCurveEditor

pytestmark = pytest.mark.gui


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


# -- tone curve ------------------------------------------------------------ #


def test_curve_identity_reports_empty(qapp: QApplication) -> None:
    editor = ToneCurveEditor()
    assert editor._canvas.active_points() == []  # untouched RGB curve is identity
    assert editor._canvas.field == "curve_rgb"


def test_curve_channel_switch_changes_field(qapp: QApplication) -> None:
    editor = ToneCurveEditor()
    editor._group.button(1).click()  # Red
    assert editor._canvas.field == "curve_red"
    editor._group.button(3).click()  # Blue
    assert editor._canvas.field == "curve_blue"


def test_curve_add_point_emits_field_and_points(qapp: QApplication) -> None:
    editor = ToneCurveEditor()
    seen: list[tuple[str, object]] = []
    editor.curve_changed.connect(lambda f, p: seen.append((f, p)))
    canvas = editor._canvas
    canvas.resize(220, 220)
    centre = canvas._to_px(128, 128)
    canvas._add_point(centre.x(), centre.y())  # add an interior control point
    assert seen and seen[-1][0] == "curve_rgb"
    assert len(seen[-1][1]) == 3  # endpoints + the new point, non-identity
    assert len(canvas.active_points()) == 3
    new_x = canvas.active_points()[1][0]
    assert 0 < new_x < 255  # interior point stays strictly inside the end points


def test_curve_set_state_roundtrip(qapp: QApplication) -> None:
    editor = ToneCurveEditor()
    state = EditState(curve_rgb=[(0, 10), (255, 240)], curve_red=[(0, 0), (100, 130), (255, 255)])
    editor.set_state(state)
    assert editor._canvas.active_points() == [(0, 10), (255, 240)]
    editor._group.button(1).click()
    assert editor._canvas.active_points() == [(0, 0), (100, 130), (255, 255)]


# -- colour wheels --------------------------------------------------------- #


def test_hsv_to_rgb_primaries(qapp: QApplication) -> None:
    hue = np.array([0.0, 120.0, 240.0])  # red, green, blue
    sat = np.array([1.0, 1.0, 1.0])
    rgb = _hsv_to_rgb(hue, sat, 1.0)
    assert tuple(rgb[0]) == (255, 0, 0)
    assert tuple(rgb[1]) == (0, 255, 0)
    assert tuple(rgb[2]) == (0, 0, 255)


def test_wheel_set_values_and_emit(qapp: QApplication) -> None:
    wheel = ColorWheel("Shadows")
    wheel.set_values(180.0, 50.0)
    assert wheel._hue == 180.0
    assert wheel._sat == pytest.approx(0.5)
    seen: list[tuple[float, float]] = []
    wheel.changed.connect(lambda h, s: seen.append((h, s)))
    wheel.changed.emit(200.0, 30.0)
    assert seen[-1] == (200.0, 30.0)


def test_grade_panel_emits_param_changed(qapp: QApplication) -> None:
    panel = ColorGradingPanel()
    seen: list[tuple[object, object, float]] = []
    panel.param_changed.connect(lambda p, s, v: seen.append((p, s, v)))
    panel._on_wheel("grade_shadow", 210.0, 35.0)
    assert ("grade_shadow_hue", None, 210.0) in seen
    assert ("grade_shadow_sat", None, 35.0) in seen


def test_grade_panel_set_state(qapp: QApplication) -> None:
    panel = ColorGradingPanel()
    state = EditState(
        grade_shadow_hue=200.0, grade_shadow_sat=60.0, grade_shadow_lum=20.0,
        grade_balance=-30.0, grade_blending=70.0,
    )
    panel.set_state(state)
    assert panel._wheels["grade_shadow"]._hue == 200.0
    assert panel._wheels["grade_shadow"]._sat == pytest.approx(0.6)
    assert panel._lum["grade_shadow"].value() == 20
    assert panel._balance.value() == -30
    assert panel._blending.value() == 70


# -- graph sections inside the adjustments panel --------------------------- #


def test_panel_embeds_graph_sections_with_mode_visibility(qapp: QApplication) -> None:
    from vibephoto.ui.adjustments_panel import ADVANCED, INTERMEDIATE, SIMPLE, AdjustmentsPanel

    panel = AdjustmentsPanel()
    assert panel.curve_editor is not None
    assert panel.grade_panel is not None
    # INTERMEDIATE widget sections (Tone Curve, Color Grading, Masks, Lens Profile)
    # are hidden in Simple and shown in Advanced. (WB and Crop are SIMPLE.)
    panel.set_mode(SIMPLE)
    graph_sections = [
        s for s, lvl, rows in panel._sections if not rows and lvl == INTERMEDIATE
    ]
    assert len(graph_sections) == 4
    assert all(s.isHidden() for s in graph_sections)
    panel.set_mode(ADVANCED)
    assert all(not s.isHidden() for s in graph_sections)


def test_panel_set_state_syncs_graphs(qapp: QApplication) -> None:
    from vibephoto.ui.adjustments_panel import AdjustmentsPanel

    panel = AdjustmentsPanel()
    panel.set_state(
        EditState(curve_rgb=[(0, 20), (255, 255)], grade_mid_hue=120.0, grade_mid_sat=50.0)
    )
    assert panel.curve_editor._canvas.active_points() == [(0, 20), (255, 255)]
    assert panel.grade_panel._wheels["grade_mid"]._hue == 120.0
