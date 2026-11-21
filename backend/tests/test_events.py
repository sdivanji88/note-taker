import queue
import threading

from note_taker.events import EventBus


def test_eventbus_fanout():
    bus = EventBus()
    a1, a2 = bus.subscribe("A"), bus.subscribe("A")
    b = bus.subscribe("B")

    bus.publish("A", "capture.status_changed", {"capture_id": "C1", "status": "ready"})

    expected = {"type": "capture.status_changed", "data": {"capture_id": "C1", "status": "ready"}}
    assert a1.get_nowait() == expected
    assert a2.get_nowait() == expected
    assert b.empty()

    bus.unsubscribe("A", a1)
    bus.publish("A", "batch.push_progress", {"stage": "done"})
    assert a1.empty()
    assert a2.get_nowait()["type"] == "batch.push_progress"


def test_publish_without_subscribers_and_double_unsubscribe_are_noops():
    bus = EventBus()
    bus.publish("A", "capture.extracted", {})
    q = bus.subscribe("A")
    bus.unsubscribe("A", q)
    bus.unsubscribe("A", q)
    bus.unsubscribe("never", queue.Queue())


def test_concurrent_publish_delivers_every_event():
    bus = EventBus()
    q = bus.subscribe("A")
    threads = [
        threading.Thread(target=lambda: [bus.publish("A", "capture.extracted", {}) for _ in range(200)])
        for _ in range(4)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert q.qsize() == 800
