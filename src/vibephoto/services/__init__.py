"""Services layer — application-level orchestration and view-models.

Coordinates domain layers into the use-cases the UI invokes (import session,
develop session, batch sync, export queue) and exposes them as injectable
services with lifecycle and progress reporting. View-models here are UI-toolkit
agnostic; the Qt layer binds to them. This is where commands (undo/redo) and
long-running job management live.

Depends on: ``core`` and the domain layers. Never imports ``ui``.
Built incrementally across phases as use-cases are added.
"""

from __future__ import annotations

__all__: list[str] = []
