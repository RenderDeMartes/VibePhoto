"""GUI bootstrap — turns a headless :class:`Application` into a running desktop app.

Creates (or reuses) the :class:`QApplication`, applies the theme, installs a
last-resort exception hook that routes unhandled GUI-thread errors to the log and
a dialog (so the app degrades gracefully instead of vanishing), shows the main
window, and runs the Qt event loop.
"""

from __future__ import annotations

import logging
import sys
from types import TracebackType

from PySide6.QtWidgets import QApplication, QMessageBox

from vibephoto import APP_AUTHOR, APP_NAME
from vibephoto.app.application import Application
from vibephoto.ui.main_window import MainWindow
from vibephoto.ui.theme import apply_theme

logger = logging.getLogger(__name__)


def _install_excepthook() -> None:
    def hook(
        exc_type: type[BaseException],
        exc: BaseException,
        tb: TracebackType | None,
    ) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        logger.critical("Unhandled exception on GUI thread", exc_info=(exc_type, exc, tb))
        try:
            QMessageBox.critical(
                None,
                f"{APP_NAME} — Unexpected Error",
                f"An unexpected error occurred:\n\n{exc_type.__name__}: {exc}\n\n"
                "The error has been logged. You may need to restart the application.",
            )
        except Exception:
            logger.exception("Failed to display error dialog")

    sys.excepthook = hook


def run_gui(app: Application) -> int:
    """Run the Qt GUI for an already-started :class:`Application`. Returns exit code."""
    qapp = QApplication.instance() or QApplication(sys.argv)
    assert isinstance(qapp, QApplication)
    qapp.setApplicationName(APP_NAME)
    qapp.setOrganizationName(APP_AUTHOR)
    qapp.setApplicationDisplayName(APP_NAME)

    apply_theme(qapp, app.settings.general)
    _install_excepthook()

    window = MainWindow(app)
    window.show()
    logger.info("GUI started")
    return qapp.exec()
