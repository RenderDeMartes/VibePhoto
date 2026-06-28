"""Tests for the event bus."""

from __future__ import annotations

from dataclasses import dataclass

from vibephoto.core.events import Event, EventBus


@dataclass(frozen=True)
class PhotoImported(Event):
    photo_id: int


@dataclass(frozen=True)
class PhotoRated(Event):
    photo_id: int
    rating: int


def test_subscribe_and_publish() -> None:
    bus = EventBus()
    received: list[int] = []
    bus.subscribe(PhotoImported, lambda e: received.append(e.photo_id))
    bus.publish(PhotoImported(42))
    assert received == [42]


def test_only_matching_type_is_delivered() -> None:
    bus = EventBus()
    imported: list[Event] = []
    rated: list[Event] = []
    bus.subscribe(PhotoImported, imported.append)
    bus.subscribe(PhotoRated, rated.append)
    bus.publish(PhotoImported(1))
    assert len(imported) == 1
    assert rated == []


def test_subscribing_to_base_event_receives_subclasses() -> None:
    bus = EventBus()
    seen: list[Event] = []
    bus.subscribe(Event, seen.append)  # a diagnostics-style firehose subscriber
    bus.publish(PhotoImported(1))
    bus.publish(PhotoRated(1, 5))
    assert len(seen) == 2


def test_unsubscribe_stops_delivery() -> None:
    bus = EventBus()
    received: list[int] = []
    sub = bus.subscribe(PhotoImported, lambda e: received.append(e.photo_id))
    bus.publish(PhotoImported(1))
    sub.unsubscribe()
    bus.publish(PhotoImported(2))
    assert received == [1]


def test_subscription_context_manager() -> None:
    bus = EventBus()
    received: list[int] = []
    with bus.subscribe(PhotoImported, lambda e: received.append(e.photo_id)):
        bus.publish(PhotoImported(1))
    bus.publish(PhotoImported(2))  # outside the context: not delivered
    assert received == [1]


def test_handler_exception_is_isolated() -> None:
    bus = EventBus()
    received: list[int] = []

    def bad(_e: PhotoImported) -> None:
        raise RuntimeError("boom")

    bus.subscribe(PhotoImported, bad)
    bus.subscribe(PhotoImported, lambda e: received.append(e.photo_id))
    bus.publish(PhotoImported(7))  # must not raise
    assert received == [7]
