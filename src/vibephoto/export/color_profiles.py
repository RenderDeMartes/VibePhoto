"""Output colour profiles for export.

Exported files must *declare* their colour space, or other apps (browsers, print
RIPs, other editors) guess — and usually guess wrong, so the colours shift. A
professional editor always embeds the output profile; we previously wrote untagged
pixels. The develop pipeline works in sRGB (see :mod:`vibephoto.processing.color`),
so the correct tag for every export is the standard sRGB ICC profile, which we
attach to the written file.

The bytes come from littlecms (via Pillow's ImageCms), so no binary profile asset
ships with the app; the lookup is cached because building the profile is the only
non-trivial cost and it never changes.
"""

from __future__ import annotations

import logging
from functools import lru_cache

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def srgb_icc_bytes() -> bytes | None:
    """Standard sRGB ICC profile bytes to embed in exports, or ``None`` if littlecms
    is unavailable (Pillow built without it) — exports then go out untagged rather
    than failing, exactly as before this profile existed."""
    try:
        from PIL import ImageCms
    except ImportError:  # Pillow without the C littlecms backend
        logger.info("ImageCms unavailable; exports will not embed an ICC profile")
        return None
    try:
        profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
        return profile.tobytes()
    except Exception:  # noqa: BLE001 — never let colour tagging break an export
        logger.warning("Could not build sRGB ICC profile; exporting untagged", exc_info=True)
        return None
