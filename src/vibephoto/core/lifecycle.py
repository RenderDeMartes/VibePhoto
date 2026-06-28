"""Service lifecycle protocol.

Long-lived services (catalog, cache, thumbnail/processing workers) need an
orderly start-up and shutdown so resources — database connections, thread pools,
file handles — are acquired and released deterministically. :class:`Service`
defines that contract; :class:`ServiceHost` starts a set of services in order and
guarantees they are stopped in reverse order, even if one fails mid-startup.

Keeping this in ``core`` (rather than tying it to Qt or a specific service) means
the same lifecycle works for the headless engine, batch tooling, and the GUI app.
"""

from __future__ import annotations

import logging
from enum import Enum, auto
from typing import Protocol, runtime_checkable

from vibephoto.core.errors import ServiceLifecycleError

logger = logging.getLogger(__name__)


class ServiceState(Enum):
    """Lifecycle state of a :class:`Service`."""

    CREATED = auto()
    STARTED = auto()
    STOPPED = auto()
    FAILED = auto()


@runtime_checkable
class Service(Protocol):
    """A component with an explicit start/stop lifecycle.

    Implementations should be idempotent where reasonable and must not raise on a
    second ``stop()``. ``name`` is used in logs and diagnostics.
    """

    @property
    def name(self) -> str: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...


class ServiceHost:
    """Starts services in registration order; stops them in reverse.

    This is the runtime backbone of the application object: register the catalog,
    caches, and worker pools, then ``start()`` once. On shutdown, ``stop()``
    tears everything down in reverse dependency order. If a service fails to
    start, already-started services are rolled back so the process never lingers
    in a half-initialised state.
    """

    def __init__(self) -> None:
        self._services: list[Service] = []
        self._started: list[Service] = []
        self._state = ServiceState.CREATED

    @property
    def state(self) -> ServiceState:
        return self._state

    def add(self, service: Service) -> ServiceHost:
        """Register a service. Must be called before :meth:`start`."""
        if self._state is not ServiceState.CREATED:
            raise ServiceLifecycleError(
                "Cannot add services after the host has started",
                context={"service": service.name},
            )
        self._services.append(service)
        return self

    def start(self) -> None:
        """Start all registered services in order, rolling back on failure."""
        if self._state is ServiceState.STARTED:
            return
        for service in self._services:
            try:
                logger.debug("Starting service %s", service.name)
                service.start()
                self._started.append(service)
            except Exception as exc:
                self._state = ServiceState.FAILED
                logger.exception("Service %s failed to start; rolling back", service.name)
                self._rollback()
                raise ServiceLifecycleError(
                    f"Service {service.name!r} failed to start: {exc}",
                    context={"service": service.name},
                ) from exc
        self._state = ServiceState.STARTED

    def stop(self) -> None:
        """Stop started services in reverse order. Never raises."""
        self._rollback()
        self._state = ServiceState.STOPPED

    def _rollback(self) -> None:
        while self._started:
            service = self._started.pop()
            try:
                logger.debug("Stopping service %s", service.name)
                service.stop()
            except Exception:
                logger.exception("Service %s raised during stop()", service.name)
