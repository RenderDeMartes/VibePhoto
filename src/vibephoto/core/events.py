"""A lightweight, typed publish/subscribe event bus.

The bus decouples producers from consumers: the catalog can announce
``PhotoImported`` without knowing the UI exists, and the UI subscribes without
reaching into the catalog. This directly supports the architectural rule that
lower layers never depend on the UI.

Dispatch is synchronous and runs on the caller's thread. Cross-thread delivery
(e.g. marshalling a worker-thread event onto the Qt GUI thread) is the
responsibility of a thin adapter in the UI layer; keeping the core bus transport-
agnostic means it stays usable in headless contexts.

Handlers are isolated: an exception in one subscriber is logged and does not
prevent other subscribers from receiving the event.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Event:
    """Base class for all events. Subclass as frozen dataclasses.

    Example::

        @dataclass(frozen=True)
        class PhotoImported(Event):
            photo_id: int
            path: str
    """


E = TypeVar("E", bound=Event)
Handler = Callable[[E], None]


class Subscription:
    """Handle returned by :meth:`EventBus.subscribe`; call to unsubscribe."""

    __slots__ = ("_active", "_bus", "_event_type", "_handler")

    def __init__(self, bus: EventBus, event_type: type[Event], handler: Handler[Any]) -> None:
        self._bus = bus
        self._event_type = event_type
        self._handler = handler
        self._active = True

    def unsubscribe(self) -> None:
        if self._active:
            self._bus._remove(self._event_type, self._handler)
            self._active = False

    def __enter__(self) -> Subscription:
        return self

    def __exit__(self, *exc: object) -> None:
        self.unsubscribe()


class EventBus:
    """Synchronous, thread-safe, type-routed event dispatcher.

    Subscribing to a base ``Event`` subclass also receives its subclasses, so a
    diagnostics panel can subscribe to ``Event`` itself to observe everything.
    """

    def __init__(self) -> None:
        self._handlers: dict[type[Event], list[Handler[Any]]] = {}
        self._lock = threading.RLock()

    def subscribe(self, event_type: type[E], handler: Handler[E]) -> Subscription:
        """Register ``handler`` for ``event_type`` (and its subclasses)."""
        with self._lock:
            self._handlers.setdefault(event_type, []).append(handler)
        return Subscription(self, event_type, handler)

    def publish(self, event: Event) -> None:
        """Deliver ``event`` to every handler registered for it or a base type."""
        # Snapshot handlers under the lock, then dispatch outside it so a handler
        # may (un)subscribe without deadlocking, and slow handlers don't block
        # other publishers.
        with self._lock:
            recipients: list[Handler[Any]] = []
            for klass in type(event).__mro__:
                if not isinstance(klass, type) or not issubclass(klass, Event):
                    continue
                handlers = self._handlers.get(klass)
                if handlers:
                    recipients.extend(handlers)

        for handler in recipients:
            try:
                handler(event)
            except Exception:
                logger.exception(
                    "Event handler %r failed for %s",
                    getattr(handler, "__qualname__", handler),
                    type(event).__name__,
                )

    def _remove(self, event_type: type[Event], handler: Handler[Any]) -> None:
        with self._lock:
            handlers = self._handlers.get(event_type)
            if not handlers:
                return
            try:
                handlers.remove(handler)
            except ValueError:
                return
            if not handlers:
                del self._handlers[event_type]
