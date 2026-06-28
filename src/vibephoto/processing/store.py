"""DevelopStore — persistence for non-destructive edits.

Each photo's :class:`LayerStack` is stored as a small JSON file under the app data
directory, keyed by photo id. Older saves that hold a single :class:`EditState`
load transparently as a one-layer stack. Writes are atomic so a crash can't
corrupt an edit.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from vibephoto.core.paths import AppPaths
from vibephoto.processing.layers import LayerStack

logger = logging.getLogger(__name__)


class DevelopStore:
    """Loads and saves a per-photo :class:`LayerStack` as a JSON sidecar."""

    def __init__(self, paths: AppPaths) -> None:
        self._dir = paths.develop_dir

    def _path(self, photo_id: int) -> Path:
        return self._dir / f"{photo_id}.json"

    def load(self, photo_id: int) -> LayerStack:
        """Return the stored edit for ``photo_id`` (empty stack if none/invalid)."""
        path = self._path(photo_id)
        if not path.is_file():
            return LayerStack.single()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Corrupt develop sidecar %s; ignoring", path)
            return LayerStack.single()
        return LayerStack.from_dict(data)

    def save(self, photo_id: int, stack: LayerStack) -> None:
        """Persist ``stack`` for ``photo_id`` atomically (deletes file if identity)."""
        path = self._path(photo_id)
        if stack.is_identity():
            path.unlink(missing_ok=True)
            return
        self._dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(stack.to_dict(), indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def clear(self, photo_id: int) -> None:
        self._path(photo_id).unlink(missing_ok=True)
