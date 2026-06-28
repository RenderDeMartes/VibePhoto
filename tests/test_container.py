"""Tests for the dependency-injection container."""

from __future__ import annotations

import pytest

from vibephoto.core.container import Container, Lifetime
from vibephoto.core.errors import DependencyResolutionError


class Engine:
    def __init__(self) -> None:
        self.id = id(self)


class Wheels:
    def __init__(self) -> None:
        self.count = 4


class Car:
    """Has two injectable dependencies, resolved by type hint."""

    def __init__(self, engine: Engine, wheels: Wheels) -> None:
        self.engine = engine
        self.wheels = wheels


# Module-level mutually-dependent classes for the cycle-detection test. They must
# be module-level so forward references resolve via module globals (which is how
# real services are defined — function-local classes are a pathological case).
class CycleA:
    def __init__(self, b: CycleB) -> None:
        self.b = b


class CycleB:
    def __init__(self, a: CycleA) -> None:
        self.a = a


def test_register_and_resolve_singleton() -> None:
    c = Container()
    c.register(Engine, Engine, Lifetime.SINGLETON)
    a = c.resolve(Engine)
    b = c.resolve(Engine)
    assert a is b


def test_transient_returns_new_instances() -> None:
    c = Container()
    c.register(Engine, Engine, Lifetime.TRANSIENT)
    assert c.resolve(Engine) is not c.resolve(Engine)


def test_constructor_injection_autowires_dependencies() -> None:
    c = Container()
    c.register(Engine)
    c.register(Wheels)
    c.register(Car)
    car = c.resolve(Car)
    assert isinstance(car.engine, Engine)
    assert isinstance(car.wheels, Wheels)
    # Singleton engine shared with a direct resolve.
    assert car.engine is c.resolve(Engine)


def test_register_instance() -> None:
    c = Container()
    engine = Engine()
    c.register_instance(Engine, engine)
    assert c.resolve(Engine) is engine


def test_register_factory_receives_resolver() -> None:
    c = Container()
    c.register(Engine)
    c.register_factory(Car, lambda r: Car(r.resolve(Engine), Wheels()), Lifetime.SINGLETON)
    car = c.resolve(Car)
    assert isinstance(car, Car)
    assert car.engine is c.resolve(Engine)


def test_interface_to_implementation_binding() -> None:
    class Repository:  # acts as the abstract "interface"
        def get(self) -> str:
            raise NotImplementedError

    class SqliteRepository(Repository):
        def get(self) -> str:
            return "sqlite"

    c = Container()
    c.register(Repository, SqliteRepository)
    repo = c.resolve(Repository)
    assert isinstance(repo, SqliteRepository)
    assert repo.get() == "sqlite"


def test_unregistered_abstract_raises() -> None:
    from abc import ABC, abstractmethod

    class Port(ABC):
        @abstractmethod
        def go(self) -> None: ...

    c = Container()
    with pytest.raises(DependencyResolutionError):
        c.resolve(Port)


def test_autobind_concrete_unregistered_class() -> None:
    c = Container()
    # Engine has no deps and is concrete -> auto-constructable as transient.
    assert isinstance(c.resolve(Engine), Engine)


def test_circular_dependency_detected() -> None:
    c = Container()
    c.register(CycleA)
    c.register(CycleB)
    with pytest.raises(DependencyResolutionError, match="Circular"):
        c.resolve(CycleA)


def test_scoped_instances_are_per_scope() -> None:
    c = Container()
    c.register(Engine, Engine, Lifetime.SCOPED)

    scope1 = c.create_scope()
    scope2 = c.create_scope()

    a1 = scope1.resolve(Engine)
    a1b = scope1.resolve(Engine)
    a2 = scope2.resolve(Engine)

    assert a1 is a1b  # same within a scope
    assert a1 is not a2  # different across scopes


def test_scoped_resolved_outside_scope_raises() -> None:
    c = Container()
    c.register(Engine, Engine, Lifetime.SCOPED)
    with pytest.raises(DependencyResolutionError, match="scoped"):
        c.resolve(Engine)


def test_container_can_resolve_itself() -> None:
    c = Container()
    assert c.resolve(Container) is c


def test_missing_type_hint_on_required_param_raises() -> None:
    class Bad:
        def __init__(self, x) -> None:  # type: ignore[no-untyped-def]
            self.x = x

    c = Container()
    c.register(Bad)
    with pytest.raises(DependencyResolutionError, match="no type hint"):
        c.resolve(Bad)
