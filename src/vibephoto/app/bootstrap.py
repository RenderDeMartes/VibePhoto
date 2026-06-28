"""Composition root — builds and wires the application.

``build_application`` is the single place that assembles the object graph:
resolve paths, load settings, configure logging, create the event bus, register
core singletons in the DI container, and register long-lived services with the
service host. As later phases land (catalog, cache, processing), their services
are registered here and *only* here — the rest of the code base depends on
abstractions resolved from the container, never on construction details.

This keeps wiring centralised and makes the dependency graph auditable in one
file, which is the maintainability payoff of dependency injection.
"""

from __future__ import annotations

import logging

from vibephoto.app.application import Application, ApplicationContext
from vibephoto.cache.thumbnails import ThumbnailCache
from vibephoto.catalog.indexer import IndexerService
from vibephoto.catalog.service import CatalogService
from vibephoto.core.config import AppSettings, CacheSettings, load_settings
from vibephoto.core.container import Container
from vibephoto.core.events import EventBus
from vibephoto.core.lifecycle import ServiceHost
from vibephoto.core.logging import configure_logging
from vibephoto.core.paths import AppPaths
from vibephoto.export.service import ExportService
from vibephoto.metadata.reader import MetadataReader
from vibephoto.presets.library import PresetLibrary
from vibephoto.processing.clipboard import SettingsClipboard
from vibephoto.processing.engine import DevelopEngine
from vibephoto.processing.loader import ImageLoader
from vibephoto.processing.recent import LastEdit
from vibephoto.processing.store import DevelopStore
from vibephoto.raw.service import RawService

logger = logging.getLogger(__name__)


def build_application(
    *,
    paths: AppPaths | None = None,
    settings: AppSettings | None = None,
    configure_logs: bool = True,
) -> Application:
    """Assemble a fully-wired, not-yet-started :class:`Application`.

    Parameters
    ----------
    paths:
        Override the resolved platform paths (tests pass a temp-dir-backed
        :meth:`AppPaths.under`). Defaults to the per-user platform locations.
    settings:
        Override the loaded settings. Defaults to loading from disk + env.
    configure_logs:
        When True, install logging handlers. Tests usually pass False to avoid
        touching global logging state.
    """
    paths = (paths or AppPaths.platform_default()).ensure()
    settings = settings if settings is not None else load_settings(paths)

    if configure_logs:
        configure_logging(settings.logging, paths)

    event_bus = EventBus()
    container = Container()

    context = ApplicationContext(
        paths=paths,
        settings=settings,
        container=container,
        event_bus=event_bus,
    )

    _register_core(container, context)
    _register_services(container)
    service_host = _build_service_host(container)

    logger.info("Application composed (paths=%s)", paths.config_dir)
    return Application(context, service_host)


def _register_core(container: Container, context: ApplicationContext) -> None:
    """Register the foundational singletons every layer may depend on."""
    container.register_instance(ApplicationContext, context)
    container.register_instance(AppSettings, context.settings)
    container.register_instance(AppPaths, context.paths)
    container.register_instance(EventBus, context.event_bus)
    # Section settings are registered individually so a service can depend on
    # just the slice it needs (e.g. ``CacheSettings``) rather than the whole tree.
    container.register_instance(type(context.settings.logging), context.settings.logging)
    container.register_instance(type(context.settings.catalog), context.settings.catalog)
    container.register_instance(type(context.settings.cache), context.settings.cache)
    container.register_instance(type(context.settings.processing), context.settings.processing)
    container.register_instance(type(context.settings.metadata), context.settings.metadata)


def _register_services(container: Container) -> None:
    """Register domain/compute services against the container.

    Registered as singletons and auto-wired by constructor type hints. Adding a
    service here (and, if long-lived, to the service host below) is the only
    wiring step a new feature needs — callers depend on the resolved abstraction.
    """
    container.register(MetadataReader)
    container.register(RawService)
    # ThumbnailCache's RAW dependency is an optional constructor arg (so it stays
    # usable standalone in tests); a factory wires the real RawService in the app.
    container.register_factory(
        ThumbnailCache,
        lambda r: ThumbnailCache(
            r.resolve(AppPaths), r.resolve(CacheSettings), r.resolve(RawService)
        ),
    )
    container.register(CatalogService)
    container.register(IndexerService)
    # Processing engine (Develop module): loader → engine, plus the edit store.
    container.register(ImageLoader)
    container.register(DevelopEngine)
    container.register(DevelopStore)
    container.register(SettingsClipboard)
    container.register(LastEdit)
    # Presets library + export engine.
    container.register(PresetLibrary)
    container.register(ExportService)


def _build_service_host(container: Container) -> ServiceHost:
    """Register long-lived services in start-up order.

    Start-up order = the order of ``.add(...)``; shutdown is the reverse. The
    catalog must start first (and stop last) so other services can rely on it.
    """
    host = ServiceHost()
    host.add(container.resolve(CatalogService))
    return host
