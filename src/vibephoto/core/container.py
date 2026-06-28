"""A small, explicit dependency-injection container.

Why a custom container rather than a framework? The project needs only a thin,
predictable slice of DI: interface→implementation binding, singleton/transient/
scoped lifetimes, and constructor injection driven by type hints. A focused
~200-line container keeps the ``core`` layer dependency-free, makes resolution
behaviour obvious when debugging, and avoids tying the architecture to a
third-party library's conventions.

The container is the seam that lets the *Processing Engine never depend on the
UI*: high layers register concrete implementations against abstract protocols,
and lower layers ask only for the protocol. Tests swap in fakes by registering
a different implementation.

Example
-------
    container = Container()
    container.register_instance(AppSettings, settings)
    container.register(ThumbnailCache, DiskThumbnailCache, Lifetime.SINGLETON)
    cache = container.resolve(ThumbnailCache)  # constructor-injected
"""

from __future__ import annotations

import inspect
import threading
import typing
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, TypeVar, get_type_hints

from vibephoto.core.errors import DependencyResolutionError

T = TypeVar("T")

#: A factory receives the resolving container/scope and returns an instance.
Factory = Callable[["Resolver"], Any]


class Lifetime(Enum):
    """How long a resolved instance lives."""

    #: One shared instance per container (created lazily, thread-safe).
    SINGLETON = auto()
    #: A fresh instance on every ``resolve`` call.
    TRANSIENT = auto()
    #: One instance per :class:`Scope`.
    SCOPED = auto()


@dataclass(slots=True)
class _Registration:
    key: type
    factory: Factory
    lifetime: Lifetime


class Resolver(typing.Protocol):
    """The resolution surface shared by :class:`Container` and :class:`Scope`."""

    def resolve(self, key: type[T]) -> T: ...


class Container:
    """Registry + resolver for application services.

    Thread-safe for singleton creation. Registration is expected to happen once,
    up front, in the composition root (see ``vibephoto.app.bootstrap``).
    """

    def __init__(self) -> None:
        self._registrations: dict[type, _Registration] = {}
        self._singletons: dict[type, Any] = {}
        self._lock = threading.RLock()
        # The container can resolve itself, which is occasionally useful for
        # factories that need to perform conditional resolution. Register it as a
        # proper instance so resolution returns *this* container, not a new one.
        self.register_instance(Container, self)

    # -- Registration ------------------------------------------------------- #

    def register(
        self,
        key: type[T],
        implementation: type[T] | None = None,
        lifetime: Lifetime = Lifetime.SINGLETON,
    ) -> Container:
        """Bind ``key`` to a concrete ``implementation`` (defaults to ``key``).

        The implementation is auto-wired: its constructor parameters are resolved
        from the container by type hint at resolution time.
        """
        impl = implementation or key
        if not isinstance(impl, type):
            raise DependencyResolutionError(
                f"Implementation for {key!r} must be a class, got {impl!r}"
            )

        def factory(resolver: Resolver, _impl: type = impl) -> Any:
            return _autowire(_impl, resolver)

        self._registrations[key] = _Registration(key, factory, lifetime)
        return self

    def register_factory(
        self,
        key: type[T],
        factory: Callable[[Resolver], T],
        lifetime: Lifetime = Lifetime.SINGLETON,
    ) -> Container:
        """Bind ``key`` to an explicit factory callable."""
        self._registrations[key] = _Registration(key, factory, lifetime)
        return self

    def register_instance(self, key: type[T], instance: T) -> Container:
        """Bind ``key`` to an already-constructed singleton instance."""
        self._registrations[key] = _Registration(
            key, lambda _r: instance, Lifetime.SINGLETON
        )
        self._singletons[key] = instance
        return self

    def is_registered(self, key: type) -> bool:
        return key in self._registrations

    # -- Resolution --------------------------------------------------------- #

    def resolve(self, key: type[T]) -> T:
        """Resolve ``key`` to an instance, constructing dependencies as needed."""
        return self._resolve(key, scope=None, stack=())

    def create_scope(self) -> Scope:
        """Create a child scope for ``Lifetime.SCOPED`` services."""
        return Scope(self)

    # -- Internal ----------------------------------------------------------- #

    def _resolve(
        self,
        key: type[T],
        *,
        scope: Scope | None,
        stack: tuple[type, ...],
    ) -> T:
        if key in stack:
            chain = " -> ".join(k.__name__ for k in (*stack, key))
            raise DependencyResolutionError(f"Circular dependency detected: {chain}")

        registration = self._registrations.get(key)
        if registration is None:
            # Auto-bind concrete, instantiable classes as transient for ergonomics.
            if isinstance(key, type) and not _is_abstract(key):
                return typing.cast(T, _autowire(key, _StackResolver(self, scope, (*stack, key))))
            # ``key`` may be a non-class (e.g. a ``X | None`` union from an
            # optional constructor param); use a name that never raises so this
            # surfaces as a catchable DependencyResolutionError — letting
            # ``_autowire`` fall back to the parameter's default.
            name = _key_name(key)
            raise DependencyResolutionError(
                f"No registration for {name!r} and it cannot be auto-constructed",
                context={"key": name},
            )

        if registration.lifetime is Lifetime.SINGLETON:
            return typing.cast(T, self._resolve_singleton(registration, scope, stack))
        if registration.lifetime is Lifetime.SCOPED:
            if scope is None:
                raise DependencyResolutionError(
                    f"{key.__name__!r} is scoped but was resolved outside a scope"
                )
            return typing.cast(T, scope._resolve_scoped(registration, stack))
        # TRANSIENT
        return typing.cast(T, registration.factory(_StackResolver(self, scope, (*stack, key))))

    def _resolve_singleton(
        self,
        registration: _Registration,
        scope: Scope | None,
        stack: tuple[type, ...],
    ) -> Any:
        existing = self._singletons.get(registration.key, _MISSING)
        if existing is not _MISSING:
            return existing
        with self._lock:
            existing = self._singletons.get(registration.key, _MISSING)
            if existing is not _MISSING:
                return existing
            instance = registration.factory(
                _StackResolver(self, scope, (*stack, registration.key))
            )
            self._singletons[registration.key] = instance
            return instance


class Scope:
    """A resolution scope owning its own ``Lifetime.SCOPED`` instances.

    Singletons are shared with the parent container; transients are fresh as
    always. A scope typically wraps a unit of work (e.g. processing one image,
    or one editing session) so scoped services share state within it.
    """

    def __init__(self, container: Container) -> None:
        self._container = container
        self._scoped: dict[type, Any] = {}

    def resolve(self, key: type[T]) -> T:
        return self._container._resolve(key, scope=self, stack=())

    def _resolve_scoped(self, registration: _Registration, stack: tuple[type, ...]) -> Any:
        existing = self._scoped.get(registration.key, _MISSING)
        if existing is not _MISSING:
            return existing
        instance = registration.factory(
            _StackResolver(self._container, self, (*stack, registration.key))
        )
        self._scoped[registration.key] = instance
        return instance


class _StackResolver:
    """Adapter passed to factories so nested resolutions keep the cycle stack."""

    __slots__ = ("_container", "_scope", "_stack")

    def __init__(self, container: Container, scope: Scope | None, stack: tuple[type, ...]) -> None:
        self._container = container
        self._scope = scope
        self._stack = stack

    def resolve(self, key: type[T]) -> T:
        return self._container._resolve(key, scope=self._scope, stack=self._stack)


class _Missing:
    __slots__ = ()


_MISSING = _Missing()


def _key_name(key: object) -> str:
    """A readable name for any resolution key, including non-class keys such as
    ``X | None`` unions (which have no ``__name__``)."""
    return getattr(key, "__name__", None) or str(key)


def _is_abstract(cls: type) -> bool:
    return bool(getattr(cls, "__abstractmethods__", False)) or inspect.isabstract(cls)


def _autowire(cls: type, resolver: Resolver) -> Any:
    """Instantiate ``cls`` by resolving its annotated constructor parameters.

    Parameters with no annotation are skipped (must have a default); parameters
    with a default are only injected when their type is registered/resolvable.
    """
    # ``signature(cls)`` returns the constructor signature with ``self`` already
    # stripped; it raises for builtins without an introspectable signature.
    try:
        signature = inspect.signature(cls)
    except (ValueError, TypeError):
        return cls()
    # ``get_type_hints`` evaluates string/forward-ref annotations against the
    # function's module globals. Forward refs to names not visible there (e.g.
    # classes defined in a local scope) raise NameError; degrade gracefully and
    # fall back to the raw signature annotations. ``getattr`` keeps mypy from
    # flagging the (here perfectly safe) ``__init__`` access on a class object.
    init_func = getattr(cls, "__init__", None)
    try:
        hints = get_type_hints(init_func) if init_func is not None else {}
    except Exception:  # noqa: BLE001 - any annotation-eval failure
        hints = {}

    empty = inspect.Parameter.empty
    kwargs: dict[str, Any] = {}
    for name, param in signature.parameters.items():
        if name == "self" or param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        has_default = param.default is not empty
        annotation = hints.get(name, param.annotation)

        if annotation is empty or annotation is None:
            if has_default:
                continue
            raise DependencyResolutionError(
                f"Cannot inject parameter {name!r} of {cls.__name__}: no type hint",
                context={"class": cls.__name__, "param": name},
            )
        if isinstance(annotation, str):  # unresolved forward reference
            if has_default:
                continue
            raise DependencyResolutionError(
                f"Cannot inject parameter {name!r} of {cls.__name__}: "
                f"unresolved annotation {annotation!r}",
                context={"class": cls.__name__, "param": name},
            )
        try:
            kwargs[name] = resolver.resolve(annotation)
        except DependencyResolutionError:
            if has_default:
                continue  # fall back to the declared default
            raise
    return cls(**kwargs)
