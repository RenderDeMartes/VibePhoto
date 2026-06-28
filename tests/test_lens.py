"""Tests for manual lens corrections (distortion, CA, vignetting)."""

from __future__ import annotations

import numpy as np

from vibephoto.processing.edit_state import EditState
from vibephoto.processing.image_buffer import ImageBuffer
from vibephoto.processing.lens import (
    correct_chromatic_aberration,
    correct_distortion,
    correct_vignetting,
)
from vibephoto.processing.pipeline import PipelineRenderer, build_stages


def _img() -> np.ndarray:
    rng = np.random.default_rng(0)
    return rng.random((48, 64, 3)).astype(np.float32)


def test_corrections_are_identity_at_zero() -> None:
    img = _img()
    assert correct_distortion(img, 0.0) is img
    assert correct_chromatic_aberration(img, 0.0) is img
    assert correct_vignetting(img, 0.0) is img


def test_distortion_changes_pixels_and_keeps_shape() -> None:
    img = _img()
    out = correct_distortion(img, 60.0)
    assert out.shape == img.shape and out.dtype == np.float32
    assert not np.allclose(out, img)


def test_vignetting_brightens_corners_more_than_centre() -> None:
    flat = np.full((40, 40, 3), 0.5, dtype=np.float32)
    out = correct_vignetting(flat, 100.0)
    corner = float(out[0, 0].mean())
    centre = float(out[20, 20].mean())
    assert corner > centre  # corners lifted, centre ~unchanged
    assert abs(centre - 0.5) < 1e-3


def test_ca_shifts_red_and_blue_oppositely() -> None:
    img = _img()
    out = correct_chromatic_aberration(img, 100.0)
    assert out.shape == img.shape
    assert not np.allclose(out[..., 0], img[..., 0])  # red channel remapped
    assert np.allclose(out[..., 1], img[..., 1])  # green untouched


def test_lens_fields_wired_into_pipeline() -> None:
    keyed = {k for stage in build_stages() for k in stage.keys}
    assert {"lens_distortion", "lens_ca", "lens_vignetting"} <= keyed
    base = ImageBuffer(_img(), "srgb")
    out = PipelineRenderer(base).render(EditState(lens_vignetting=80.0))
    assert not np.allclose(out.data, base.data)
    assert EditState().is_identity()  # lens defaults are a no-op


def test_lens_geometry_skipped_in_draft() -> None:
    draft = {s.name for s in build_stages(draft=True)}
    assert "lens_geometry" not in draft  # expensive remap deferred while dragging
    assert "lens_vignetting" in draft  # cheap gain stays live


def test_lens_profiles_define_fisheye_defish() -> None:
    from vibephoto.processing.lens import (
        AUTO_LENS_PROFILE,
        LENS_PROFILE_NAMES,
        LENS_PROFILES,
    )

    assert "None" in LENS_PROFILES and LENS_PROFILES["None"] == (0.0, 0.0, 0.0)
    assert AUTO_LENS_PROFILE in LENS_PROFILES
    distortion, _ca, _vig = LENS_PROFILES[AUTO_LENS_PROFILE]
    assert distortion >= 80.0  # the auto-fix is a strong defish
    assert len(LENS_PROFILE_NAMES) >= 4


def test_named_lens_profiles_and_groups() -> None:
    from vibephoto.processing.lens import (
        LENS_PROFILE_GROUPS,
        LENS_PROFILES,
        detect_lens_profile,
    )

    groups = {g for g, _ in LENS_PROFILE_GROUPS}
    assert {"Generic", "Canon", "Sony"} <= groups
    assert "Canon EF 8-15mm f/4L Fisheye" in LENS_PROFILES
    assert "Sony FE 12-24mm f/4 G" in LENS_PROFILES
    # A Canon 8-15 fisheye in the EXIF resolves to that exact lens, not the generic.
    assert detect_lens_profile("EF8-15mm f/4L Fisheye USM", 10.0) == "Canon EF 8-15mm f/4L Fisheye"
    # A Sony body + 16-35 prefers the Sony profile.
    assert detect_lens_profile("FE 16-35mm F2.8 GM", 20.0, "ILCE-7M4") == "Sony FE 16-35mm f/2.8 GM"


def test_lens_profile_store_roundtrip(tmp_path) -> None:
    from vibephoto.processing.lens_store import LensProfileStore

    store = LensProfileStore(tmp_path)
    assert store.load() == {}
    store.save("My Fisheye", (95.0, 8.0, 30.0))
    assert store.load()["My Fisheye"] == (95.0, 8.0, 30.0)
    store.save("My Fisheye", (50.0, 0.0, 0.0))  # overwrite
    assert store.load()["My Fisheye"] == (50.0, 0.0, 0.0)
    store.delete("My Fisheye")
    assert store.load() == {}


def test_detect_lens_profile_from_metadata() -> None:
    from vibephoto.processing.lens import detect_lens_profile

    # Fisheye named in the lens string.
    assert detect_lens_profile("Samyang 8mm Fisheye", 8.0) == "Fisheye — Full (180°)"
    assert detect_lens_profile("Generic Diagonal Fisheye 12mm", 12.0) == "Fisheye — Diagonal"
    # Action cam by camera model.
    assert detect_lens_profile(None, None, "GoPro HERO11") == "Action cam (wide)"
    # Focal-length buckets when no fisheye keyword.
    assert detect_lens_profile("Laowa 7.5mm", 7.5) == "Ultra-wide"
    assert detect_lens_profile("Sigma 14mm", 14.0) == "Wide-angle"
    assert detect_lens_profile("Canon 50mm", 50.0) == "None"  # normal lens, no fix
    # No information to decide from.
    assert detect_lens_profile(None, None, None) is None
    # Tolerant of messy EXIF: string focal lengths and junk values.
    assert detect_lens_profile(None, "8 mm") == "Ultra-wide"
    assert detect_lens_profile(None, "not-a-number") is None  # unparseable + no name
    assert detect_lens_profile(None, 0) is None  # zero/invalid focal, no lens name


def test_strong_distortion_defishes_more_at_edges() -> None:
    # A bright ring near the edge moves inward under a strong defish.
    img = np.zeros((81, 81, 3), dtype=np.float32)
    img[40, 70:78, :] = 1.0  # a mark out toward the right edge
    out = correct_distortion(img, 100.0)
    # Brightness that was at the far edge is pulled in toward centre.
    assert float(out[40, 70:78].sum()) < float(img[40, 70:78].sum())
    assert float(out[40, 55:70].sum()) > 0.0  # appears further in
