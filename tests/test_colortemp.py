"""Tests for as-shot colour-temperature estimation from camera calibration."""

from __future__ import annotations

from vibephoto.raw.colortemp import as_shot_temperature

# Real calibration read from a Canon EOS (5D-era) CR2: as-shot WB multipliers and
# the rgb_xyz_matrix. The known-good CCT for these is ~5339 K (daylight).
_CANON_WB = (2097.0, 1024.0, 1694.0, 1024.0)
_CANON_XYZ_TO_CAM = (
    (0.7034, -0.0804, -0.1014),
    (-0.442, 1.2564, 0.2058),
    (-0.0851, 0.1994, 0.5758),
    (0.0, 0.0, 0.0),
)


def test_canon_daylight_temperature() -> None:
    cct = as_shot_temperature(_CANON_WB, _CANON_XYZ_TO_CAM)
    assert cct is not None
    assert 5200 <= cct <= 5500  # ~5339 K, a daylight value


def test_warmer_light_reads_lower_kelvin() -> None:
    # A tungsten-ish shot needs a big red multiplier; its CCT should be lower.
    tungsten_wb = (1.2, 1.0, 3.0, 1.0)
    daylight = as_shot_temperature(_CANON_WB, _CANON_XYZ_TO_CAM)
    tungsten = as_shot_temperature(tungsten_wb, _CANON_XYZ_TO_CAM)
    assert daylight is not None and tungsten is not None
    assert tungsten < daylight


def test_degenerate_inputs_return_none() -> None:
    singular = ((1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (3.0, 0.0, 0.0))
    assert as_shot_temperature(_CANON_WB, singular) is None  # singular matrix
    assert as_shot_temperature((0.0, 0.0, 0.0, 0.0), _CANON_XYZ_TO_CAM) is None  # zero green
    assert as_shot_temperature((1.0, 1.0), _CANON_XYZ_TO_CAM) is None  # wrong shape


def test_result_is_clamped_to_sane_range() -> None:
    cct = as_shot_temperature(_CANON_WB, _CANON_XYZ_TO_CAM)
    assert cct is not None and 2000.0 <= cct <= 50000.0
