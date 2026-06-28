"""Generate ``synthetic.dng`` — a tiny, valid Bayer DNG used as a test fixture.

The committed ``synthetic.dng`` lets ``test_raw_integration.py`` exercise the real
LibRaw decode path in CI without committing a large (or copyrighted) camera RAW.
It intentionally has *no* embedded JPEG preview, so it also covers RawService's
half-size-render fallback.

Regenerate with::

    pip install tifffile
    python tests/data/make_synthetic_dng.py

Requires ``tifffile`` (not a project dependency — only needed to rebuild the
fixture, which rarely changes).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import tifffile

WIDTH, HEIGHT = 128, 96
OUT = Path(__file__).with_name("synthetic.dng")


def main() -> None:
    # A horizontal gradient laid onto an RGGB Bayer grid — deterministic so the
    # fixture is byte-stable across regenerations.
    _, xx = np.mgrid[0:HEIGHT, 0:WIDTH]
    mosaic = ((xx / WIDTH) * 4000).astype(np.uint16) + 50

    # Roughly-identity XYZ->camera matrix (SRATIONAL) so LibRaw builds a profile.
    color_matrix = [(1, 1), (0, 1), (0, 1), (0, 1), (1, 1), (0, 1), (0, 1), (0, 1), (1, 1)]
    cm_flat = tuple(v for pair in color_matrix for v in pair)

    extratags = [
        (50706, 1, 4, (1, 4, 0, 0), True),       # DNGVersion
        (50707, 1, 4, (1, 3, 0, 0), True),       # DNGBackwardVersion
        (50708, 2, 0, "SyntheticCam", True),     # UniqueCameraModel
        (33421, 3, 2, (2, 2), True),             # CFARepeatPatternDim
        (33422, 1, 4, (0, 1, 1, 2), True),       # CFAPattern (RGGB)
        (50710, 1, 3, (0, 1, 2), True),          # CFAPlaneColor (RGB)
        (50711, 3, 1, 1, True),                  # CFALayout (rectangular)
        (50714, 3, 1, 50, True),                 # BlackLevel
        (50717, 3, 1, 4095, True),               # WhiteLevel
        (50721, 10, 9, cm_flat, True),           # ColorMatrix1 (SRATIONAL)
        (50778, 3, 1, 21, True),                 # CalibrationIlluminant1 (D65)
    ]
    tifffile.imwrite(
        OUT, mosaic, photometric=32803, compression=1,
        planarconfig="contig", extratags=extratags,
    )
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
