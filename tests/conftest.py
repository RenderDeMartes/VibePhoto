"""Shared pytest fixtures.

All fixtures keep the application's filesystem footprint inside pytest's
``tmp_path`` so tests never touch the developer's real config/cache directories
and can run fully in parallel.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from vibephoto.core.config import AppSettings
from vibephoto.core.paths import AppPaths


@pytest.fixture
def app_paths(tmp_path: Path) -> AppPaths:
    """An :class:`AppPaths` rooted in a temp dir, with directories created."""
    return AppPaths.under(tmp_path).ensure()


@pytest.fixture
def default_settings() -> AppSettings:
    """A fresh, default settings tree."""
    return AppSettings()


# A factory that writes a JPEG with EXIF, for catalog/metadata/thumbnail tests.
JpegFactory = Callable[..., Path]


@pytest.fixture
def make_jpeg() -> JpegFactory:
    """Return a factory ``make_jpeg(path, *, size, make, model, datetime_, color)``."""
    from PIL import Image

    def _make(
        path: Path,
        *,
        size: tuple[int, int] = (800, 600),
        make: str = "Canon",
        model: str = "Canon EOS R5",
        datetime_: str | None = "2024:01:15 10:30:00",
        color: tuple[int, int, int] = (120, 90, 60),
        orientation: int = 1,
    ) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        img = Image.new("RGB", size, color)
        exif = Image.Exif()
        exif[271] = make
        exif[272] = model
        exif[274] = orientation
        if datetime_:
            exif[306] = datetime_
        img.save(path, format="JPEG", exif=exif, quality=90)
        return path

    return _make
