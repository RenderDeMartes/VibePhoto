"""Tests for the XMP preset importer."""

from __future__ import annotations

from pathlib import Path

import pytest

from vibephoto.presets.xmp_import import PresetParseError, edit_state_from_xmp, load_preset

_SYNTHETIC_XMP = """<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"
   crs:Temperature="6500"
   crs:Tint="+10"
   crs:Exposure2012="+0.50"
   crs:Contrast2012="+25"
   crs:Highlights2012="-40"
   crs:Shadows2012="+30"
   crs:Clarity2012="+15"
   crs:Vibrance="+20"
   crs:SaturationAdjustmentRed="-30"
   crs:HueAdjustmentBlue="+12"
   crs:ConvertToGrayscale="False"
   crs:SplitToningShadowHue="220"
   crs:SplitToningShadowSaturation="15"
   crs:Sharpness="45"
   crs:PostCropVignetteAmount="-22">
   <crs:Name>
    <rdf:Alt><rdf:li xml:lang="x-default">Test Look</rdf:li></rdf:Alt>
   </crs:Name>
   <crs:ToneCurvePV2012>
    <rdf:Seq>
     <rdf:li>0, 15</rdf:li>
     <rdf:li>255, 240</rdf:li>
    </rdf:Seq>
   </crs:ToneCurvePV2012>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
"""

@pytest.fixture
def synthetic(tmp_path: Path) -> Path:
    path = tmp_path / "look.xmp"
    path.write_text(_SYNTHETIC_XMP, encoding="utf-8")
    return path


def test_maps_basic_fields(synthetic: Path) -> None:
    name, state = load_preset(synthetic)
    assert name == "Test Look"
    assert state.exposure == 0.5
    assert state.contrast == 25
    assert state.highlights == -40
    assert state.shadows == 30
    assert state.clarity == 15
    assert state.vibrance == 20
    assert state.temp > 0  # 6500K is warmer than the 5500K reference
    assert state.tint == 10


def test_maps_hsl_split_curve_and_effects(synthetic: Path) -> None:
    state = edit_state_from_xmp(synthetic)
    assert state.hsl_sat["red"] == -30
    assert state.hsl_hue["blue"] == 12
    assert state.grade_shadow_hue == 220  # from SplitToningShadowHue
    assert state.grade_shadow_sat == 15
    assert state.curve_rgb == [(0, 15), (255, 240)]
    assert state.sharpen_amount == 45
    assert state.vignette_amount == -22
    assert state.grayscale is False


def test_non_numeric_and_missing_fields_use_defaults(tmp_path: Path) -> None:
    xmp = tmp_path / "weird.xmp"
    xmp.write_text(
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description rdf:about="" '
        'xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/" '
        'crs:Exposure2012="not-a-number" crs:WhiteBalance="As Shot"/>'
        "</rdf:RDF></x:xmpmeta>",
        encoding="utf-8",
    )
    state = edit_state_from_xmp(xmp)
    assert state.exposure == 0.0  # unparseable -> default
    assert state.is_identity()


def test_malformed_xml_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.xmp"
    bad.write_text("this is not xml", encoding="utf-8")
    with pytest.raises(PresetParseError):
        edit_state_from_xmp(bad)
