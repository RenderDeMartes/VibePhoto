# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Vibe Photo desktop app (one-folder bundle, all platforms).

Build via ``python scripts/build_exe.py`` (or ``pyinstaller packaging/VibePhoto.spec``).
Bundles the ``vibephoto`` package data (theme QSS), the rawpy/LibRaw native
binaries, and excludes the heavy Qt modules Vibe Photo never uses to keep the
bundle smaller. On macOS a ``VibePhoto.app`` bundle is additionally produced.
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

_ROOT = Path(SPECPATH).resolve().parent  # noqa: F821 - SPECPATH injected by PyInstaller

# Theme stylesheet + py.typed marker shipped inside the package.
datas = collect_data_files("vibephoto")
# rawpy ships the LibRaw DLL as a bundled dynamic library.
binaries = collect_dynamic_libs("rawpy")

# Qt is large; drop the subsystems Vibe Photo does not use.
excludes = [
    "tkinter",
    "matplotlib",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebChannel",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtDesigner",
    "PySide6.QtTest",
    "PySide6.QtSql",
    "PySide6.QtBluetooth",
    "PySide6.QtSerialPort",
    "PySide6.QtNfc",
    "PySide6.QtSensors",
    "PySide6.QtPositioning",
    "PySide6.QtTextToSpeech",
]

a = Analysis(  # noqa: F821 - Analysis injected by PyInstaller
    [str(Path(SPECPATH) / "vibephoto_entry.py")],  # noqa: F821
    pathex=[str(_ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=["rawpy", "cv2"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
# Drop large binaries a QtWidgets-only photo app never loads: the QML/Quick/3D/PDF
# Qt modules, the software-OpenGL fallback, and Pillow's AVIF codec. This trims the
# bundle by tens of MB. (Verified the app still launches after removal.)
_BINARY_DENYLIST = (
    "qt6quick",
    "qt6qml",
    "qt6pdf",
    "qt63d",
    "qt6shadertools",
    "qt6quickwidgets",
    "qt6network",         # no networking in the app
    "libcrypto-3-x64",    # Qt's OpenSSL (the "-x64" copy); Python keeps its own
    "libssl-3-x64",
    "opengl32sw",
    "_avif",
)
a.binaries = [
    entry for entry in a.binaries
    if not any(token in entry[0].lower() for token in _BINARY_DENYLIST)
]

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VibePhoto",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # GUI app: no console window
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="VibePhoto",
)

if sys.platform == "darwin":
    app = BUNDLE(  # noqa: F821 - BUNDLE injected by PyInstaller (macOS only)
        coll,
        name="VibePhoto.app",
        icon=None,
        bundle_identifier="com.vibephoto.app",
        info_plist={
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "12.0",
        },
    )
