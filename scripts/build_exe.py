"""Build the Vibe Photo Windows executable with PyInstaller.

Usage::

    python scripts/build_exe.py

Produces a one-folder bundle at ``dist/VibePhoto/`` whose launcher is
``dist/VibePhoto/VibePhoto.exe``. Requires the build tooling::

    pip install -e .[build]

This is the canonical "create the executable" step for the project (see
``CLAUDE.md``).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "packaging" / "VibePhoto.spec"
EXE = ROOT / "dist" / "VibePhoto" / "VibePhoto.exe"


def main() -> int:
    if not SPEC.is_file():
        print(f"error: spec not found at {SPEC}", file=sys.stderr)
        return 1
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(SPEC)]
    print("Running:", " ".join(cmd))
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        return result.returncode
    if EXE.is_file():
        print(f"\nBuilt executable: {EXE}")
        return 0
    print("\nPyInstaller finished but the expected exe is missing.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
