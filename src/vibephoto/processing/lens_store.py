"""Persistence for user-defined ("My Lenses") lens-correction profiles.

A user can save the current Distortion / Defringe / Vignetting amounts as a named
profile; they are stored as JSON in the app data dir and offered alongside the
built-in Canon / Sony / Generic profiles. Headless (no Qt) so it is testable.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

Triple = tuple[float, float, float]


class LensProfileStore:
    """CRUD for custom lens profiles, persisted to ``lens_profiles.json``."""

    def __init__(self, data_dir: Path) -> None:
        self._path = Path(data_dir) / "lens_profiles.json"

    def load(self) -> dict[str, Triple]:
        """All saved profiles as ``name -> (distortion, ca, vignetting)``."""
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        out: dict[str, Triple] = {}
        if isinstance(raw, dict):
            for name, value in raw.items():
                try:
                    d, ca, vig = (float(v) for v in value)
                except (TypeError, ValueError):
                    continue
                out[str(name)] = (d, ca, vig)
        return out

    def save(self, name: str, values: Triple) -> None:
        """Add or replace a custom profile, then persist."""
        name = name.strip()
        if not name:
            return
        profiles = self.load()
        profiles[name] = (float(values[0]), float(values[1]), float(values[2]))
        self._write(profiles)

    def delete(self, name: str) -> None:
        profiles = self.load()
        if profiles.pop(name, None) is not None:
            self._write(profiles)

    def _write(self, profiles: dict[str, Triple]) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps({k: list(v) for k, v in profiles.items()}, indent=2),
                encoding="utf-8",
            )
        except OSError:
            logger.warning("Could not write lens profiles to %s", self._path, exc_info=True)
