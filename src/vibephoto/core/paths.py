"""Cross-platform application path resolution.

All filesystem locations the app uses at runtime — config, catalogs, the preview
cache, logs — are resolved through :class:`AppPaths` so the rest of the code base
never hard-codes platform-specific directories. This keeps Windows, macOS, and
Linux behaviour correct and makes tests trivially relocatable by injecting an
``AppPaths`` pointed at a temporary directory.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import platformdirs

from vibephoto import APP_AUTHOR, APP_SLUG


@dataclass(frozen=True, slots=True)
class AppPaths:
    """Resolved root directories for application data.

    Use :meth:`platform_default` for the real OS locations, or construct directly
    with a temp root in tests. All accessors return directories that are created
    on demand via :meth:`ensure`.
    """

    config_dir: Path
    data_dir: Path
    cache_dir: Path
    log_dir: Path

    @classmethod
    def platform_default(cls) -> AppPaths:
        """Resolve standard per-user directories for the current OS.

        * Windows: ``%APPDATA%/Vibe Photo`` and ``%LOCALAPPDATA%/Vibe Photo``
        * macOS:   ``~/Library/Application Support/Vibe Photo`` etc.
        * Linux:   XDG base dirs (``~/.config``, ``~/.local/share``, ``~/.cache``)
        """
        dirs = platformdirs.PlatformDirs(appname=APP_SLUG, appauthor=APP_AUTHOR, roaming=False)
        return cls(
            config_dir=Path(dirs.user_config_dir),
            data_dir=Path(dirs.user_data_dir),
            cache_dir=Path(dirs.user_cache_dir),
            log_dir=Path(dirs.user_log_dir),
        )

    @classmethod
    def under(cls, root: Path) -> AppPaths:
        """Build an :class:`AppPaths` rooted at a single directory.

        Handy for tests and for a future ``--portable`` mode that keeps everything
        next to the executable.
        """
        root = Path(root)
        return cls(
            config_dir=root / "config",
            data_dir=root / "data",
            cache_dir=root / "cache",
            log_dir=root / "logs",
        )

    @property
    def settings_file(self) -> Path:
        """Path to the user settings JSON file."""
        return self.config_dir / "settings.json"

    @property
    def catalogs_dir(self) -> Path:
        """Default directory in which new catalogs are created."""
        return self.data_dir / "catalogs"

    @property
    def previews_dir(self) -> Path:
        """Root of the preview / smart-preview cache."""
        return self.cache_dir / "previews"

    @property
    def thumbnails_dir(self) -> Path:
        """Root of the thumbnail cache."""
        return self.cache_dir / "thumbnails"

    @property
    def develop_dir(self) -> Path:
        """Where per-photo non-destructive edits (EditState JSON) are stored."""
        return self.data_dir / "develop"

    @property
    def presets_dir(self) -> Path:
        """The user's preset library (imported professional RAW editors ``.xmp`` presets)."""
        return self.data_dir / "presets"

    @property
    def exports_dir(self) -> Path:
        """Default destination for exported images."""
        return self.data_dir / "exports"

    def ensure(self) -> AppPaths:
        """Create all root directories if they do not yet exist; return self."""
        for path in (
            self.config_dir,
            self.data_dir,
            self.cache_dir,
            self.log_dir,
            self.catalogs_dir,
            self.previews_dir,
            self.thumbnails_dir,
            self.develop_dir,
            self.presets_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
        return self
