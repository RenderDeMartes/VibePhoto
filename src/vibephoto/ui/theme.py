"""Theme application for the Qt UI.

Applies a coherent dark theme by combining a :class:`QPalette` (so native widgets
and dialogs pick up the colours) with the stylesheet in
``resources/themes/dark.qss`` (for fine-grained widget styling). Keeping the
palette and QSS in agreement avoids the common half-themed look where dialogs
stay light while the main window is dark.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from vibephoto.core.config import GeneralSettings
from vibephoto.resources import resource_path

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ThemeColors:
    """Colour tokens for a theme. Mirrors the tokens documented in dark.qss."""

    bg_app: str
    bg_panel: str
    bg_elevated: str
    border: str
    text: str
    text_muted: str
    accent: str


DARK = ThemeColors(
    bg_app="#1e1f22",
    bg_panel="#26282c",
    bg_elevated="#2f3236",
    border="#3a3d42",
    text="#e6e7e9",
    text_muted="#9a9da3",
    accent="#3d8bfd",
)


def _build_palette(c: ThemeColors) -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(c.bg_app))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(c.text))
    palette.setColor(QPalette.ColorRole.Base, QColor(c.bg_panel))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(c.bg_elevated))
    palette.setColor(QPalette.ColorRole.Text, QColor(c.text))
    palette.setColor(QPalette.ColorRole.Button, QColor(c.bg_elevated))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(c.text))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(c.accent))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(c.bg_panel))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(c.text))
    disabled = QColor(c.text_muted)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, disabled)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, disabled)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, disabled)
    return palette


def _load_stylesheet(name: str) -> str:
    path = resource_path("themes", name)
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        logger.warning("Theme stylesheet %s not found; using palette only", path)
        return ""


def apply_theme(app: QApplication, settings: GeneralSettings) -> None:
    """Apply the configured theme to a running :class:`QApplication`.

    ``light`` and ``system`` are accepted by config but currently fall back to the
    dark theme; additional palettes plug in here without touching callers.
    """
    app.setStyle("Fusion")  # consistent cross-platform base for custom theming
    app.setPalette(_build_palette(DARK))
    app.setStyleSheet(_load_stylesheet("dark.qss"))
    logger.debug("Applied theme: %s", settings.theme)
