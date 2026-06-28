"""Command-line entry point for Vibe Photo.

Resolves configuration, builds the headless :class:`Application`, and — unless
``--headless`` is given — launches the Qt UI on top of it. The UI module is
imported lazily so that ``python -m vibephoto --headless`` (and the entire
non-GUI test suite) works on machines without PySide6 installed.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from vibephoto import APP_NAME, __version__
from vibephoto.app.bootstrap import build_application
from vibephoto.core.paths import AppPaths


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="vibephoto", description=f"{APP_NAME} — RAW editor")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Start the application core without launching the GUI.",
    )
    parser.add_argument(
        "--portable",
        metavar="DIR",
        type=Path,
        default=None,
        help="Store all config/data/cache under DIR instead of the OS user dirs.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Process entry point. Returns a process exit code."""
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    paths = AppPaths.under(args.portable) if args.portable else AppPaths.platform_default()
    app = build_application(paths=paths)
    log = logging.getLogger("vibephoto.main")

    try:
        app.start()
        if args.headless:
            log.info("%s %s started in headless mode.", APP_NAME, __version__)
            return 0

        # Lazy import keeps the GUI dependency optional.
        try:
            from vibephoto.ui.run import run_gui
        except ImportError as exc:  # PySide6 not installed
            log.error(
                "GUI dependencies are not installed (%s). "
                "Try: pip install 'vibephoto[ui]'",
                exc,
            )
            return 2
        return run_gui(app)
    finally:
        app.stop()


if __name__ == "__main__":
    raise SystemExit(main())
