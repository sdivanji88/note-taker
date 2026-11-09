import queue
import threading


class EventBus:
    """Per-batch fan-out from worker threads to SSE subscribers.

    Event types: capture.status_changed, capture.extracted, batch.push_progress.
    Queues are unbounded so a publisher (the extraction worker or a push) never blocks
    on a slow or vanished browser tab; subscribers unsubscribe when their stream closes.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._subs: dict[str, list[queue.Queue]] = {}

    def publish(self, batch_id: str, type: str, data: dict) -> None:
        with self._lock:
            targets = list(self._subs.get(batch_id, ()))
        event = {"type": type, "data": data}
        for q in targets:
            q.put_nowait(event)

    def subscribe(self, batch_id: str) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._subs.setdefault(batch_id, []).append(q)
        return q

    def unsubscribe(self, batch_id: str, q: queue.Queue) -> None:
        # Idempotent: a stream may be torn down both by disconnect and by cleanup.
        with self._lock:
            subs = self._subs.get(batch_id)
            if subs and q in subs:
                subs.remove(q)
                if not subs:
                    del self._subs[batch_id]
