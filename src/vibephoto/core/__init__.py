"""Core foundation layer.

This package holds the framework-level infrastructure that every other layer
builds on: the dependency-injection container, configuration, logging, the
event bus, the service-lifecycle protocol, platform path resolution, and the
exception hierarchy.

Design rule: ``core`` depends on nothing in the project except the standard
library and small pure-Python helpers (``platformdirs``). It must never import
``ui``, ``catalog``, ``processing`` or any other domain layer — those depend on
``core``, not the other way around.
"""

from __future__ import annotations

from vibephoto.core.container import Container, Lifetime
from vibephoto.core.errors import (
    ConfigError,
    DependencyResolutionError,
    VibePhotoError,
)
from vibephoto.core.events import Event, EventBus
from vibephoto.core.lifecycle import Service, ServiceState

__all__ = [
    "ConfigError",
    "Container",
    "DependencyResolutionError",
    "Event",
    "EventBus",
    "Lifetime",
    "Service",
    "ServiceState",
    "VibePhotoError",
]
