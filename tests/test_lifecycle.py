"""Tests for the service lifecycle host."""

from __future__ import annotations

import pytest

from vibephoto.core.errors import ServiceLifecycleError
from vibephoto.core.lifecycle import ServiceHost, ServiceState


class RecordingService:
    def __init__(self, name: str, log: list[str], *, fail_on_start: bool = False) -> None:
        self._name = name
        self._log = log
        self._fail = fail_on_start

    @property
    def name(self) -> str:
        return self._name

    def start(self) -> None:
        if self._fail:
            raise RuntimeError("cannot start")
        self._log.append(f"start:{self._name}")

    def stop(self) -> None:
        self._log.append(f"stop:{self._name}")


def test_starts_in_order_stops_in_reverse() -> None:
    log: list[str] = []
    host = ServiceHost()
    host.add(RecordingService("a", log)).add(RecordingService("b", log))
    host.start()
    assert host.state is ServiceState.STARTED
    host.stop()
    assert host.state is ServiceState.STOPPED
    assert log == ["start:a", "start:b", "stop:b", "stop:a"]


def test_failure_rolls_back_started_services() -> None:
    log: list[str] = []
    host = ServiceHost()
    host.add(RecordingService("a", log))
    host.add(RecordingService("b", log, fail_on_start=True))
    host.add(RecordingService("c", log))
    with pytest.raises(ServiceLifecycleError):
        host.start()
    assert host.state is ServiceState.FAILED
    # 'a' started then got rolled back; 'c' never started.
    assert log == ["start:a", "stop:a"]


def test_cannot_add_after_start() -> None:
    host = ServiceHost()
    host.add(RecordingService("a", []))
    host.start()
    with pytest.raises(ServiceLifecycleError):
        host.add(RecordingService("b", []))


def test_stop_is_safe_when_never_started() -> None:
    ServiceHost().stop()  # must not raise


def test_double_start_is_noop() -> None:
    log: list[str] = []
    host = ServiceHost()
    host.add(RecordingService("a", log))
    host.start()
    host.start()
    assert log == ["start:a"]
