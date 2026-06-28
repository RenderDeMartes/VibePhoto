"""UI layer — the PySide6 (Qt) desktop front-end.

This is the *only* layer permitted to import Qt. It consumes an already-built
:class:`~vibephoto.app.application.Application` and binds widgets to services
and view-models resolved from the DI container. Nothing below this layer imports
``ui``; that one-directional dependency is what keeps the processing engine and
catalog runnable headless.

Importing this package requires PySide6. Code paths that must stay GUI-optional
import from here lazily (see ``vibephoto.__main__``).
"""

from __future__ import annotations

__all__ = ["run_gui"]


def __getattr__(name: str) -> object:
    # Lazy attribute access so `import vibephoto.ui` doesn't hard-require Qt
    # until something is actually used.
    if name == "run_gui":
        from vibephoto.ui.run import run_gui

        return run_gui
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
