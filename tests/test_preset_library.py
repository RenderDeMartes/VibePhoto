"""Tests for the user preset library (scan + import)."""

from __future__ import annotations

from pathlib import Path

from vibephoto.core.paths import AppPaths
from vibephoto.presets.library import PresetLibrary

_XMP = "<x:xmpmeta xmlns:x='adobe:ns:meta/'></x:xmpmeta>"


def _library(tmp_path: Path) -> PresetLibrary:
    return PresetLibrary(AppPaths.under(tmp_path).ensure())


def test_empty_library_lists_nothing(tmp_path: Path) -> None:
    assert _library(tmp_path).list_presets() == []


def test_import_folder_copies_xmp_files(tmp_path: Path) -> None:
    pack = tmp_path / "MyPack"
    pack.mkdir()
    (pack / "Alpha.xmp").write_text(_XMP, encoding="utf-8")
    (pack / "Beta.xmp").write_text(_XMP, encoding="utf-8")
    (pack / "notes.txt").write_text("ignore", encoding="utf-8")

    library = _library(tmp_path)
    count = library.import_folder(pack)
    assert count == 2

    names = [name for name, _ in library.list_presets()]
    assert names == ["Alpha", "Beta"]  # sorted, .txt ignored


def test_import_file(tmp_path: Path) -> None:
    src = tmp_path / "Look.xmp"
    src.write_text(_XMP, encoding="utf-8")
    library = _library(tmp_path)
    dest = library.import_file(src)
    assert dest is not None and dest.exists()
    assert [name for name, _ in library.list_presets()] == ["Look"]


def test_import_folder_of_missing_dir_is_zero(tmp_path: Path) -> None:
    assert _library(tmp_path).import_folder(tmp_path / "nope") == 0


def test_lists_both_xmp_and_lrtemplate(tmp_path: Path) -> None:
    pack = tmp_path / "Mixed"
    pack.mkdir()
    (pack / "a.xmp").write_text(_XMP, encoding="utf-8")
    (pack / "b.lrtemplate").write_text("s = { value = { settings = {} } }", encoding="utf-8")
    library = _library(tmp_path)
    assert library.import_folder(pack) == 2  # both formats copied
    assert sorted(name for name, _ in library.list_presets()) == ["a", "b"]


def test_list_groups_by_folder(tmp_path: Path) -> None:
    library = _library(tmp_path)
    root = library.directory
    (root / "PackA").mkdir(parents=True)
    (root / "PackA" / "one.xmp").write_text(_XMP, encoding="utf-8")
    (root / "PackA" / "two.lrtemplate").write_text("s={value={settings={}}}", encoding="utf-8")
    (root / "loose.xmp").write_text(_XMP, encoding="utf-8")

    groups = dict(library.list_groups())
    assert set(groups) == {"General", "PackA"}
    assert [name for name, _ in groups["General"]] == ["loose"]
    assert sorted(name for name, _ in groups["PackA"]) == ["one", "two"]
