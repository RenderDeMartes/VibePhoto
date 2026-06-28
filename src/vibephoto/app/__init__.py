"""Application layer.

This layer is the *composition root*: it wires the foundation and (later) the
domain/compute services together into a runnable :class:`Application`. It is the
only place that knows about many layers at once. Crucially, it can construct a
fully functional **headless** application — no Qt, no UI — which the test suite,
batch tooling, and future server/CLI front-ends all rely on.
"""

from __future__ import annotations

from vibephoto.app.application import Application, ApplicationContext
from vibephoto.app.bootstrap import build_application

__all__ = ["Application", "ApplicationContext", "build_application"]
