"""The user's preset library — folders of imported presets (``.xmp`` / ``.lrtemplate``).

Presets live under :attr:`AppPaths.presets_dir`, organised into subfolders (one per
imported pack). The library can list everything flat or grouped by folder, so the
UI can offer a folder picker and a preset picker. Importing a folder copies its
preset files in under a subfolder named after the source.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from vibephoto.core.paths import AppPaths
from vibephoto.presets.loaders import PRESET_EXTENSIONS

logger = logging.getLogger(__name__)

#: Folder label used for presets sitting directly in the presets root.
GENERAL_GROUP = "General"


class PresetLibrary:
    """Lists and imports presets under the user's presets directory."""

    def __init__(self, paths: AppPaths) -> None:
        self._dir = paths.presets_dir

    @property
    def directory(self) -> Path:
        return self._dir

    def _is_preset(self, path: Path) -> bool:
        return path.is_file() and path.suffix.lower() in PRESET_EXTENSIONS

    def list_presets(self) -> list[tuple[str, Path]]:
        """All presets as ``(display_name, path)`` pairs, sorted by name."""
        self._dir.mkdir(parents=True, exist_ok=True)
        items = [(p.stem, p) for p in self._dir.rglob("*") if self._is_preset(p)]
        items.sort(key=lambda item: item[0].lower())
        return items

    def list_groups(self) -> list[tuple[str, list[tuple[str, Path]]]]:
        """Presets grouped by folder: ``[(folder_name, [(name, path), …]), …]``.

        Each immediate subfolder is a group; presets in the root go under
        :data:`GENERAL_GROUP`. Empty groups are omitted; groups and presets are
        sorted by name.
        """
        self._dir.mkdir(parents=True, exist_ok=True)
        groups: list[tuple[str, list[tuple[str, Path]]]] = []

        root_items = sorted(
            ((p.stem, p) for p in self._dir.glob("*") if self._is_preset(p)),
            key=lambda item: item[0].lower(),
        )
        if root_items:
            groups.append((GENERAL_GROUP, root_items))

        for sub in sorted(d for d in self._dir.iterdir() if d.is_dir()):
            items = sorted(
                ((p.stem, p) for p in sub.rglob("*") if self._is_preset(p)),
                key=lambda item: item[0].lower(),
            )
            if items:
                groups.append((sub.name, items))
        return groups

    def import_folder(self, source: Path) -> int:
        """Copy every preset file under ``source`` into the library. Returns the count."""
        source = Path(source)
        if not source.is_dir():
            return 0
        dest_root = self._dir / source.name
        dest_root.mkdir(parents=True, exist_ok=True)
        count = 0
        for preset in source.rglob("*"):
            if self._is_preset(preset):
                try:
                    shutil.copy2(preset, dest_root / preset.name)
                    count += 1
                except OSError:
                    logger.warning("Could not import preset %s", preset)
        logger.info("Imported %d presets from %s", count, source)
        return count

    def import_file(self, source: Path) -> Path | None:
        """Copy a single preset file into the library; return its new path."""
        source = Path(source)
        if not self._is_preset(source):
            return None
        self._dir.mkdir(parents=True, exist_ok=True)
        dest = self._dir / source.name
        try:
            shutil.copy2(source, dest)
        except OSError:
            return None
        return dest
