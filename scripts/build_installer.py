"""Build the Vibe Photo Windows installer end to end.

Steps:
  1. Build the PyInstaller one-folder bundle (``scripts/build_exe.py``).
  2. Compile ``packaging/VibePhoto.iss`` with the Inno Setup compiler (ISCC.exe).

Produces ``dist/VibePhoto-Setup-<version>.exe``.

Prerequisites::

    pip install -e .[build]              # PyInstaller
    # Inno Setup 6 (free): https://jrsoftware.org/isdl.php

Usage::

    python scripts/build_installer.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ISS = ROOT / "packaging" / "VibePhoto.iss"
BUNDLE = ROOT / "dist" / "VibePhoto" / "VibePhoto.exe"


def _app_version() -> str:
    sys.path.insert(0, str(ROOT / "src"))
    try:
        from vibephoto import __version__

        return __version__
    except Exception:  # noqa: BLE001 — version is best-effort; fall back
        return "0.1.0"


def _find_iscc() -> str | None:
    """Locate the Inno Setup compiler on PATH or in its default install dirs."""
    on_path = shutil.which("ISCC") or shutil.which("iscc")
    if on_path:
        return on_path
    program_dirs = (
        os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
        os.environ.get("PROGRAMFILES", r"C:\Program Files"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs"),  # winget per-user
    )
    for base in program_dirs:
        if not base:
            continue
        candidate = Path(base) / "Inno Setup 6" / "ISCC.exe"
        if candidate.is_file():
            return str(candidate)
    return None


def main() -> int:
    # 1. PyInstaller bundle.
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_exe.py")], cwd=ROOT)
    if result.returncode != 0:
        return result.returncode
    if not BUNDLE.is_file():
        print(f"error: PyInstaller bundle missing at {BUNDLE}", file=sys.stderr)
        return 1

    # 2. Inno Setup compile.
    iscc = _find_iscc()
    if iscc is None:
        print(
            "error: Inno Setup compiler (ISCC.exe) not found.\n"
            "Install Inno Setup 6 from https://jrsoftware.org/isdl.php, then re-run.",
            file=sys.stderr,
        )
        return 2
    version = _app_version()
    cmd = [iscc, f"/DMyAppVersion={version}", str(ISS)]
    print("Running:", " ".join(cmd))
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        return result.returncode

    # The .iss writes a single fixed-name installer in the repo root, overwriting
    # any previous one — so there is always exactly one installer to find.
    installer = ROOT / "VibePhoto-Setup.exe"
    if not installer.is_file():
        print("\nISCC finished but the expected installer is missing.", file=sys.stderr)
        return 1
    print(f"\nBuilt installer: {installer}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
