"""Tests for the legacy ``.lrtemplate`` (Lua) preset reader."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from vibephoto.presets.loaders import is_preset, load_preset
from vibephoto.presets.lrtemplate_import import edit_state_from_lrtemplate, load_lrtemplate
from vibephoto.presets.mapping import PresetParseError

_LRT = textwrap.dedent(
    """\
    s = {
        id = "ABC",
        internalName = "Moody Film",
        title = "Moody Film",
        type = "Develop",
        value = {
            settings = {
                Exposure2012 = 0.5,
                Contrast2012 = 30,
                Shadows2012 = 25,
                Vibrance = -12,
                SaturationAdjustmentRed = -25,
                ConvertToGrayscale = false,
                SplitToningShadowHue = 215,
                ToneCurvePV2012 = {
                    0, 10,
                    255, 240,
                },
                MaskGroupBasedCorrections = {
                    { Exposure2012 = 9.9, LocalContrast2012 = 50 },
                },
            },
        },
        version = 0,
    }
    """
)


@pytest.fixture
def lrt(tmp_path: Path) -> Path:
    path = tmp_path / "Moody Film.lrtemplate"
    path.write_text(_LRT, encoding="utf-8")
    return path


def test_parses_scalars_and_curve(lrt: Path) -> None:
    name, state = load_lrtemplate(lrt)
    assert name == "Moody Film"
    assert state.exposure == 0.5
    assert state.contrast == 30
    assert state.shadows == 25
    assert state.vibrance == -12
    assert state.hsl_sat["red"] == -25
    assert state.grade_shadow_hue == 215
    assert state.grayscale is False
    assert state.curve_rgb == [(0, 10), (255, 240)]


def test_nested_mask_table_does_not_shadow_global(lrt: Path) -> None:
    # The 9.9 inside the mask table must not override the global Exposure2012=0.5.
    assert edit_state_from_lrtemplate(lrt).exposure == 0.5


def test_loaders_dispatch_by_extension(lrt: Path) -> None:
    assert is_preset(lrt)
    name, state = load_preset(lrt)  # dispatches to the lrtemplate reader
    assert name == "Moody Film" and state.exposure == 0.5


def test_falls_back_to_filename_when_untitled(tmp_path: Path) -> None:
    path = tmp_path / "Untitled.lrtemplate"
    path.write_text("s = { value = { settings = { Exposure2012 = 1.0 } } }", encoding="utf-8")
    name, state = load_lrtemplate(path)
    assert name == "Untitled" and state.exposure == 1.0


def test_missing_settings_raises(tmp_path: Path) -> None:
    path = tmp_path / "broken.lrtemplate"
    path.write_text('s = { title = "x" }', encoding="utf-8")
    with pytest.raises(PresetParseError):
        load_lrtemplate(path)
