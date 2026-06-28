"""Resources package — bundled, importable assets.

Holds packaged assets shipped with the application: Qt stylesheet themes, icons,
default export/develop presets, and (later) camera/ICC colour profiles. Assets
are accessed via :func:`importlib.resources` so they resolve correctly whether
running from source or from a PyInstaller/Briefcase bundle.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path


def resource_path(*parts: str) -> Path:
    """Return the filesystem path to a bundled resource under this package.

    Example: ``resource_path("themes", "dark.qss")``.
    """
    root = resources.files(__name__)
    target = root.joinpath(*parts)
    return Path(str(target))
