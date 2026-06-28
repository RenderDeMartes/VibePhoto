"""The runnable application object.

:class:`Application` bundles the resolved configuration, paths, DI container,
event bus, and service host into a single lifecycle-managed object. It is
deliberately UI-agnostic: ``Application`` knows how to start and stop the
headless core. The GUI front-end (``vibephoto.ui``) consumes an already-built
``Application`` and adds a Qt event loop on top — it is never imported here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from types import TracebackType
from typing import TypeVar

from vibephoto.core.config import AppSettings
from vibephoto.core.container import Container
from vibephoto.core.events import EventBus
from vibephoto.core.lifecycle import ServiceHost, ServiceState
from vibephoto.core.paths import AppPaths

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class ApplicationContext:
    """Immutable bundle of the application's foundational singletons.

    Passed around (and registered in the container) so any service can reach the
    settings, paths, event bus, or container without global state.
    """

    paths: AppPaths
    settings: AppSettings
    container: Container
    event_bus: EventBus


class Application:
    """Owns the application lifecycle for the headless core.

    Use as a context manager to guarantee shutdown::

        with build_application() as app:
            catalog = app.resolve(CatalogService)
            ...
    """

    def __init__(self, context: ApplicationContext, service_host: ServiceHost) -> None:
        self._context = context
        self._service_host = service_host

    # -- Accessors ---------------------------------------------------------- #

    @property
    def context(self) -> ApplicationContext:
        return self._context

    @property
    def settings(self) -> AppSettings:
        return self._context.settings

    @property
    def paths(self) -> AppPaths:
        return self._context.paths

    @property
    def events(self) -> EventBus:
        return self._context.event_bus

    @property
    def container(self) -> Container:
        return self._context.container

    @property
    def state(self) -> ServiceState:
        return self._service_host.state

    def resolve(self, key: type[T]) -> T:
        """Resolve a service from the container (convenience passthrough)."""
        return self._context.container.resolve(key)

    # -- Lifecycle ---------------------------------------------------------- #

    def start(self) -> Application:
        """Start all registered background services."""
        logger.info("Starting Vibe Photo application services")
        self._service_host.start()
        return self

    def stop(self) -> None:
        """Stop all services in reverse order. Safe to call more than once."""
        logger.info("Stopping Vibe Photo application services")
        self._service_host.stop()

    def __enter__(self) -> Application:
        return self.start()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()
