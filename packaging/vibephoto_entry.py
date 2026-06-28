"""PyInstaller entry point for the Vibe Photo desktop application.

A thin wrapper around :func:`vibephoto.__main__.main` so PyInstaller has a concrete
script to analyse. Building from a script (rather than ``-m vibephoto``) keeps the
frozen entry point explicit and stable.
"""

from __future__ import annotations

import sys

from vibephoto.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
