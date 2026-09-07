from __future__ import annotations

from ocring.ui.event_bus import EventBus, UIEvent


def test_event_bus_publishes_and_notifies_subscribers() -> None:
    bus = EventBus()
    received = []

    bus.subscribe(UIEvent.SCAN_STARTED, lambda message: received.append((message.event_type, message.payload)))
    bus.publish(UIEvent.SCAN_STARTED, {"session_id": "s1"})

    assert received == [(UIEvent.SCAN_STARTED, {"session_id": "s1"})]
    assert bus.history()[0].event_type is UIEvent.SCAN_STARTED


def test_event_bus_unsubscribe_stops_future_notifications() -> None:
    bus = EventBus()
    received = []

    unsubscribe = bus.subscribe(UIEvent.CAPTURE_LOST, lambda message: received.append(message.payload))
    unsubscribe()
    bus.publish(UIEvent.CAPTURE_LOST, {"reason": "WINDOW_LOST"})

    assert received == []


def test_event_bus_supports_capture_recovered() -> None:
    bus = EventBus()
    received = []

    bus.subscribe(UIEvent.CAPTURE_RECOVERED, lambda message: received.append(message.payload))
    bus.publish(UIEvent.CAPTURE_RECOVERED, {"reason": "WINDOW_BACK"})

    assert received == [{"reason": "WINDOW_BACK"}]
