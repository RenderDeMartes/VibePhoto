"""GUI tests for the RAW White Balance workflow (Kelvin panel + eyedropper)."""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from vibephoto.processing.edit_state import EditState
from vibephoto.processing.scene_linear import WB_REFERENCE_K
from vibephoto.ui.adjustments_panel import AdjustmentsPanel
from vibephoto.ui.white_balance_panel import WhiteBalancePanel

pytestmark = pytest.mark.gui


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


# -- the panel widget ------------------------------------------------------ #


def test_temp_slider_emits_wb_kelvin(qapp: QApplication) -> None:
    panel = WhiteBalancePanel()
    seen: list[tuple[object, object, float]] = []
    panel.param_changed.connect(lambda p, s, v: seen.append((p, s, v)))
    panel._temp.setValue(7200)
    assert ("wb_kelvin", None, 7200.0) in seen


def test_tint_slider_emits_wb_tint(qapp: QApplication) -> None:
    panel = WhiteBalancePanel()
    seen: list[tuple[object, object, float]] = []
    panel.param_changed.connect(lambda p, s, v: seen.append((p, s, v)))
    panel._tint.setValue(-30)
    assert ("wb_tint", None, -30.0) in seen


def test_set_values_syncs_without_emitting(qapp: QApplication) -> None:
    panel = WhiteBalancePanel()
    seen: list[object] = []
    panel.param_changed.connect(lambda *a: seen.append(a))
    panel.set_values(4800.0, 12.0)
    assert panel._temp.value() == 4800
    assert panel._tint.value() == 12
    assert "4800 K" in panel._temp_value.text()
    assert seen == []  # syncing the UI must not echo change signals


def test_picker_button_toggles_signal(qapp: QApplication) -> None:
    panel = WhiteBalancePanel()
    seen: list[bool] = []
    panel.picker_toggled.connect(seen.append)
    panel._picker.click()
    assert seen == [True]
    panel._picker.click()
    assert seen == [True, False]


# -- adjustments panel integration ----------------------------------------- #


def test_raw_mode_shows_wb_and_hides_relative_sliders(qapp: QApplication) -> None:
    panel = AdjustmentsPanel()
    panel.set_raw_mode(True)
    assert not panel._wb_section.isHidden()
    assert panel._rows[("temp", None)].isHidden()  # relative Temp/Tint hidden for RAW
    assert panel._rows[("tint", None)].isHidden()


def test_non_raw_hides_wb_and_shows_relative_sliders(qapp: QApplication) -> None:
    panel = AdjustmentsPanel()
    panel.set_raw_mode(False)
    assert panel._wb_section.isHidden()
    assert not panel._rows[("temp", None)].isHidden()


def test_highlight_recovery_slider_is_raw_only(qapp: QApplication) -> None:
    panel = AdjustmentsPanel()
    row = panel._rows[("highlight_recovery", None)]
    assert row.raw_only
    panel.set_raw_mode(True)
    assert not row.isHidden()  # shown for RAW
    panel.set_raw_mode(False)
    assert row.isHidden()  # hidden for JPEG (it lives in the scene-linear chain)


def test_set_state_syncs_wb_panel(qapp: QApplication) -> None:
    panel = AdjustmentsPanel()
    panel.set_state(EditState(wb_kelvin=3300.0, wb_tint=-8.0))
    assert panel.white_balance._temp.value() == 3300
    assert panel.white_balance._tint.value() == -8


def test_wb_panel_resets_to_reference(qapp: QApplication) -> None:
    panel = WhiteBalancePanel()
    panel.set_values(3000.0, 40.0)
    panel.set_values(WB_REFERENCE_K, 0.0)
    assert panel._temp.value() == int(WB_REFERENCE_K)
    assert panel._tint.value() == 0


# -- true-Kelvin display calibration --------------------------------------- #


def test_reference_makes_slider_show_true_as_shot_temperature(qapp: QApplication) -> None:
    panel = WhiteBalancePanel()
    panel.set_reference(5339.0)  # the camera's true as-shot CCT
    panel.set_values(WB_REFERENCE_K, 0.0)  # engine "as shot" (6500-anchored)
    assert panel._temp.value() == 5339  # ...displays the real temperature
    assert "5339 K" in panel._temp_value.text()


def test_displayed_kelvin_converts_back_to_engine_value(qapp: QApplication) -> None:
    panel = WhiteBalancePanel()
    panel.set_reference(5339.0)
    seen: list[float] = []
    panel.param_changed.connect(lambda p, s, v: seen.append(v) if p == "wb_kelvin" else None)
    panel._temp.setValue(4500)  # user drags to a cooler true Kelvin
    # engine wb_kelvin = displayed - ref + 6500 = 4500 - 5339 + 6500 = 5661
    assert seen and round(seen[-1]) == 5661
