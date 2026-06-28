"""Project-wide exception hierarchy.

A single rooted hierarchy lets callers catch ``VibePhotoError`` to handle any
application-originated failure while still allowing precise ``except`` clauses.
Layers define their own subclasses (e.g. ``CatalogError``, ``RawDecodeError``)
rooted here so cross-cutting concerns — logging, the global exception hook,
user-facing error dialogs — can reason about errors uniformly.
"""

from __future__ import annotations


class VibePhotoError(Exception):
    """Base class for all errors raised intentionally by Vibe Photo.

    Carries an optional machine-readable ``code`` and a ``context`` mapping that
    the logging layer serialises and the UI layer can surface to the user.
    """

    #: Stable, machine-readable identifier for this error category. Subclasses
    #: may override; useful for telemetry and for mapping to localized messages.
    code: str = "vibephoto.error"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        context: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        self.context: dict[str, object] = dict(context or {})

    def __str__(self) -> str:  # pragma: no cover - trivial
        if self.context:
            return f"{self.message} (context={self.context!r})"
        return self.message


class ConfigError(VibePhotoError):
    """Raised when configuration cannot be loaded, parsed, or validated."""

    code = "vibephoto.config"


class DependencyResolutionError(VibePhotoError):
    """Raised by the DI container when a dependency cannot be resolved."""

    code = "vibephoto.di"


class ServiceLifecycleError(VibePhotoError):
    """Raised when a service is started/stopped in an invalid state."""

    code = "vibephoto.lifecycle"


class PluginError(VibePhotoError):
    """Base class for plugin-loading / plugin-runtime failures."""

    code = "vibephoto.plugin"
