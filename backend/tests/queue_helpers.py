"""Shared helpers for the extraction queue test modules."""

import threading
import time
from datetime import timedelta

from conftest import dt

from note_taker.batch_store import BatchStore
from note_taker.events import EventBus
from note_taker.extraction_queue import ExtractionQueue
from note_taker.extractors.base import HealthStatus
from note_taker.models import ExtractedHighlight, ExtractionResult


class Clock:
    """Strictly increasing time, so any touch of updated_at would be observable."""

    def __init__(self):
        self.t = dt(2026, 11, 1)

    def __call__(self):
        self.t += timedelta(minutes=1)
        return self.t


class GatedExtractor:
    """First call blocks until released (a hung model); later calls return at once."""

    name = "gated"

    def __init__(self, result: ExtractionResult | None = None):
        self.result = result or ExtractionResult(highlights=[ExtractedHighlight(text="late")])
        self.started = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()
        self._first = True
        self.calls: list = []

    def health(self) -> HealthStatus:
        return HealthStatus(ok=True, detail="ok")

    def extract(self, image_path, rotation=0):
        self.calls.append((image_path.name, rotation))
        if self._first:
            self._first = False
            self.started.set()
            self.release.wait(5)
            self.finished.set()
            return self.result
        return ExtractionResult(highlights=[ExtractedHighlight(text="quick")])


def wait_until(cond, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.01)
    raise AssertionError("condition not met in time")


def queue_env(data_paths, make_image):
    """Body of each module's `env` fixture: a store, bus and queue factory; stops queues after."""
    store = BatchStore(data_paths, now=Clock())
    bus = EventBus()
    queues: list[ExtractionQueue] = []

    def add(batch_id, name, **kw):
        p = make_image(name, highlight_text=name)
        cap = store.add_photo(batch_id, name, p.read_bytes())
        if kw:
            store.modify(batch_id, lambda b: _set(b, cap.id, **kw))
        return cap.id

    def make_queue(extractor, **kw):
        kw.setdefault("health_interval_s", 60)
        q = ExtractionQueue(store, lambda kind: extractor, bus, **kw)
        queues.append(q)
        return q

    def cap(batch_id, cid):
        return next((c for c in store.get(batch_id).captures if c.id == cid), None)

    class Env:
        pass

    e = Env()
    e.store, e.bus, e.add, e.queue, e.cap = store, bus, add, make_queue, cap
    yield e
    for q in queues:
        q.stop()


def _set(batch, cid, **fields):
    for c in batch.captures:
        if c.id == cid:
            for k, v in fields.items():
                setattr(c, k, v)


def status(e, b, cid):
    c = e.cap(b, cid)
    return c.status if c else None


def _drain(q):
    out = []
    while not q.empty():
        ev = q.get_nowait()
        out.append((ev["type"], ev["data"]))
    return out


class Blocking:
    """An extractor whose calls block until released, so tests can order two runs exactly."""

    def __init__(self, name, block_health=False):
        self.name = name
        self.block_health = block_health
        self.health_started = threading.Event()
        self.started = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()
        self.rotations: list[int] = []

    def health(self) -> HealthStatus:
        if self.block_health:
            self.health_started.set()
            self.release.wait(5)
        return HealthStatus(ok=True, detail="ok")

    def extract(self, image_path, rotation=0):
        self.rotations.append(rotation)
        self.started.set()
        if not self.block_health:
            self.release.wait(5)
        self.finished.set()
        return ExtractionResult(highlights=[ExtractedHighlight(text=self.name)])
