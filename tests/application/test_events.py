from ATS.application.events import EventBus
from ATS.core.events import Event, EventType


def test_event_bus_isolates_listener_failures():
    seen = []
    bus = EventBus()
    bus.subscribe(lambda _event: (_ for _ in ()).throw(RuntimeError("listener failed")))
    bus.subscribe(seen.append)

    event = Event(type=EventType.RUN_STARTED, run_id="r")
    bus.emit(event)

    assert seen == [event]


def test_unsubscribe_stops_delivery():
    seen = []
    bus = EventBus()
    unsubscribe = bus.subscribe(seen.append)
    unsubscribe()
    bus.emit(Event(type=EventType.RUN_STARTED, run_id="r"))
    assert seen == []
