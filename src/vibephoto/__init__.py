"""Vibe Photo — a professional RAW photo editor and catalog manager.

The package is organised into strictly layered subpackages. The foundational
invariant is that compute and domain layers never import the UI layer, so the
entire processing core can run headless. See ``docs/02-technical-architecture.md``.
"""

from __future__ import annotations

__all__ = ["APP_AUTHOR", "APP_NAME", "APP_SLUG", "__version__"]

#: Human-facing application name.
APP_NAME = "Vibe Photo"

#: Filesystem-safe slug used for config/cache directory names.
APP_SLUG = "vibephoto"

#: Vendor/author name used for platform config directories.
APP_AUTHOR = "Vibe Photo"

#: Semantic version. Kept in sync with ``pyproject.toml``.
__version__ = "0.1.2"
