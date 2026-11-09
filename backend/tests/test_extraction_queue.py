import threading
import time
from datetime import timedelta

import pytest

from note_taker import imaging
from note_taker.batch_store import BatchStore
from note_taker.events import EventBus
from note_taker.extraction_queue import ExtractionQueue
from note_taker.extractors.base import ExtractionError, HealthStatus
from note_taker.extractors.factory import build_extractor
from note_taker.extractors.fake import FakeExtractor
from note_taker.models import (
    CaptureStatus,
    ExtractedHighlight,
    ExtractionResult,
    ExtractorKind,
    ExtractorSettings,
)
from conftest import dt


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


@pytest.fixture(autouse=True)
def no_osd(monkeypatch):
    # Rotation detection is exercised explicitly; elsewhere it must be inert and fast.
    monkeypatch.setattr(imaging, "detect_rotation", lambda path: 0)


@pytest.fixture
def env(data_paths, make_image):
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


def test_queue_success_sets_ready_and_note_on_first_highlight(env):
    b = env.store.create(None).id
    cid = env.add(b, "a.png")
    result = ExtractionResult(
        highlights=[ExtractedHighlight(text="one"), ExtractedHighlight(text="two")],
        note="margin note",
        page=163,
        chapter="Chapter 12",
    )
    events = env.bus.subscribe(b)
    q = env.queue(FakeExtractor(result=result))
    q.start()
    q.enqueue(b, cid)
    wait_until(lambda: status(env, b, cid) == CaptureStatus.ready)
    c = env.cap(b, cid)
    assert [h.text for h in c.highlights] == ["one", "two"]
    assert [h.note for h in c.highlights] == ["margin note", None]
    assert (c.page, c.chapter, c.extractor_used, c.error) == (163, "Chapter 12", "fake", None)
    seen = []
    wait_until(lambda: seen.extend(_drain(events)) or "capture.extracted" in [t for t, _ in seen])
    statuses = [d["status"] for t, d in seen if t == "capture.status_changed"]
    assert statuses == ["extracting", "ready"]
    assert all(d["capture_id"] == cid for _, d in seen)


def _drain(q):
    out = []
    while not q.empty():
        ev = q.get_nowait()
        out.append((ev["type"], ev["data"]))
    return out


def test_queue_keeps_page_and_chapter_the_user_already_set(env):
    b = env.store.create(None).id
    cid = env.add(b, "a.png", page=12, chapter="Mine")
    q = env.queue(FakeExtractor(result=ExtractionResult(page=99, chapter="Theirs")))
    q.start()
    q.enqueue(b, cid)
    wait_until(lambda: status(env, b, cid) == CaptureStatus.ready)
    c = env.cap(b, cid)
    assert (c.page, c.chapter) == (12, "Mine")


def test_queue_empty_result_is_ready_with_no_highlights(env):
    b = env.store.create(None).id
    cid = env.add(b, "a.png")
    q = env.queue(FakeExtractor(result=ExtractionResult()))
    q.start()
    q.enqueue(b, cid)
    wait_until(lambda: status(env, b, cid) == CaptureStatus.ready)
    assert env.cap(b, cid).highlights == []


def test_queue_error_sets_failed(env):
    b = env.store.create(None).id
    cid = env.add(b, "a.png")
    q = env.queue(FakeExtractor(error="model said no"))
    q.start()
    q.enqueue(b, cid)
    wait_until(lambda: status(env, b, cid) == CaptureStatus.failed)
    assert env.cap(b, cid).error == "model said no"


def test_queue_unexpected_exception_sets_failed_and_worker_survives(env):
    class Boom(FakeExtractor):
        def extract(self, image_path, rotation=0):
            if image_path.name.startswith(self.bad):
                raise RuntimeError("kaboom")
            return super().extract(image_path, rotation)

    b = env.store.create(None).id
    c1, c2 = env.add(b, "a.png"), env.add(b, "b.png")
    ext = Boom()
    ext.bad = env.cap(b, c1).image_file
    q = env.queue(ext)
    q.start()
    q.enqueue(b, c1)
    q.enqueue(b, c2)
    wait_until(lambda: status(env, b, c2) == CaptureStatus.ready)
    assert status(env, b, c1) == CaptureStatus.failed
    assert "kaboom" in env.cap(b, c1).error


def test_queue_timeout_sets_failed(env):
    b = env.store.create(None).id
    cid = env.add(b, "a.png")
    q = env.queue(FakeExtractor(delay_s=2), timeout_s=0.2)
    q.start()
    q.enqueue(b, cid)
    wait_until(lambda: status(env, b, cid) == CaptureStatus.failed, timeout=1.5)
    assert env.cap(b, cid).error == "timed out after 0.2s"


def test_late_outcome_after_timeout_is_ignored(env):
    b = env.store.create(None).id
    c1, c2 = env.add(b, "a.png"), env.add(b, "b.png")
    ext = GatedExtractor()
    q = env.queue(ext, timeout_s=0.2)
    q.start()
    q.enqueue(b, c1)
    wait_until(lambda: status(env, b, c1) == CaptureStatus.failed)
    ext.release.set()
    assert ext.finished.wait(2)
    # A later job going through proves the worker has moved on past any late result.
    q.enqueue(b, c2)
    wait_until(lambda: status(env, b, c2) == CaptureStatus.ready)
    c = env.cap(b, c1)
    assert (c.status, c.error, c.highlights) == (CaptureStatus.failed, "timed out after 0.2s", [])


def test_stuck_extractor_does_not_starve_next_job(env):
    b = env.store.create(None).id
    c1, c2 = env.add(b, "a.png"), env.add(b, "b.png")
    ext = GatedExtractor()
    q = env.queue(ext, timeout_s=0.2)
    q.start()
    q.enqueue(b, c1)
    q.enqueue(b, c2)
    # c1 is still hung (never released) while c2 must complete on a fresh thread.
    wait_until(lambda: status(env, b, c2) == CaptureStatus.ready)
    assert status(env, b, c1) == CaptureStatus.failed
    assert not ext.finished.is_set()
    ext.release.set()


def test_discarded_mid_extraction_is_not_resurrected(env):
    b = env.store.create(None).id
    c1, c2 = env.add(b, "a.png"), env.add(b, "b.png")
    ext = GatedExtractor()
    q = env.queue(ext)
    q.start()
    q.enqueue(b, c1)
    assert ext.started.wait(2)
    env.store.modify(b, lambda batch: _set(batch, c1, status=CaptureStatus.discarded))
    ext.release.set()
    q.enqueue(b, c2)
    wait_until(lambda: status(env, b, c2) == CaptureStatus.ready)
    c = env.cap(b, c1)
    assert (c.status, c.highlights, c.extractor_used) == (CaptureStatus.discarded, [], None)


def test_removed_mid_extraction_is_not_resurrected(env):
    b = env.store.create(None).id
    c1, c2 = env.add(b, "a.png"), env.add(b, "b.png")
    ext = GatedExtractor()
    q = env.queue(ext)
    q.start()
    q.enqueue(b, c1)
    assert ext.started.wait(2)
    env.store.remove_capture(b, c1)
    ext.release.set()
    q.enqueue(b, c2)
    wait_until(lambda: status(env, b, c2) == CaptureStatus.ready)
    assert env.cap(b, c1) is None
    assert [c.id for c in env.store.get(b).captures] == [c2]


def test_requeued_mid_extraction_drops_stale_outcome_and_runs_again(env):
    b = env.store.create(None).id
    cid = env.add(b, "a.png")
    ext = GatedExtractor()
    q = env.queue(ext)
    q.start()
    q.enqueue(b, cid)
    assert ext.started.wait(2)
    # The user hits "retry" while the first attempt is still running.
    env.store.modify(b, lambda batch: _set(batch, cid, status=CaptureStatus.pending))
    q.enqueue(b, cid)
    ext.release.set()
    wait_until(lambda: status(env, b, cid) == CaptureStatus.ready)
    assert [h.text for h in env.cap(b, cid).highlights] == ["quick"]


def test_deleted_batch_mid_extraction_is_dropped(env):
    b = env.store.create(None).id
    c1 = env.add(b, "a.png")
    b2 = env.store.create(None).id
    c2 = env.add(b2, "b.png")
    ext = GatedExtractor()
    q = env.queue(ext)
    q.start()
    q.enqueue(b, c1)
    assert ext.started.wait(2)
    env.store.delete(b)
    ext.release.set()
    q.enqueue(b2, c2)
    wait_until(lambda: status(env, b2, c2) == CaptureStatus.ready)
    assert [x.id for x in env.store.list()] == [b2]


def test_queue_unhealthy_leaves_pending_then_resumes(env):
    b = env.store.create(None).id
    cid = env.add(b, "a.png")
    ext = FakeExtractor(healthy=False)
    q = env.queue(ext)
    q.start()
    q.enqueue(b, cid)
    wait_until(lambda: (env.cap(b, cid).error or "").startswith("extractor unavailable: "))
    assert status(env, b, cid) == CaptureStatus.pending
    assert ext.calls == []
    ext.healthy = True
    assert q.resume_pending() == 1
    wait_until(lambda: status(env, b, cid) == CaptureStatus.ready)
    assert env.cap(b, cid).error is None


def test_health_loop_resumes_pending_automatically(env):
    b = env.store.create(None).id
    cid = env.add(b, "a.png")
    ext = FakeExtractor(healthy=False)
    q = env.queue(ext, health_interval_s=0.05)
    q.start()
    q.enqueue(b, cid)
    wait_until(lambda: env.cap(b, cid).error is not None)
    ext.healthy = True
    wait_until(lambda: status(env, b, cid) == CaptureStatus.ready)


def test_provider_failure_is_reported_as_unavailable(env):
    b = env.store.create(None).id
    cid = env.add(b, "a.png")
    store_kind_log = []

    def provider(kind):
        store_kind_log.append(kind)
        raise NotImplementedError("ollama extractor arrives in Task 8")

    q = ExtractionQueue(env.store, provider, env.bus, health_interval_s=60)
    try:
        q.enqueue(b, cid, ExtractorKind.ollama)
        q.start()
        wait_until(lambda: env.cap(b, cid).error is not None)
        c = env.cap(b, cid)
        assert c.status == CaptureStatus.pending
        assert c.error.startswith("extractor unavailable: ")
        assert store_kind_log == [ExtractorKind.ollama]
    finally:
        q.stop()


def test_queue_does_not_touch_updated_at(env):
    b = env.store.create(None).id
    cid = env.add(b, "a.png")
    before = env.store.get(b).updated_at
    q = env.queue(FakeExtractor(result=ExtractionResult(highlights=[ExtractedHighlight(text="x")])))
    q.start()
    q.enqueue(b, cid)
    wait_until(lambda: status(env, b, cid) == CaptureStatus.ready)
    assert env.store.get(b).updated_at == before


def test_queue_fifo_order(env):
    b1 = env.store.create(None).id
    b2 = env.store.create(None).id
    c1, c2 = env.add(b1, "a.png"), env.add(b1, "b.png")
    c3 = env.add(b2, "c.png")
    ext = FakeExtractor()
    q = env.queue(ext)
    order = [(b2, c3), (b1, c2), (b1, c1)]
    for bid, cid in order:
        q.enqueue(bid, cid)
    q.start()
    wait_until(lambda: len(ext.calls) == 3)
    files = [env.cap(bid, cid).image_file for bid, cid in order]
    assert [path.name for path, _ in ext.calls] == files


def test_enqueue_twice_extracts_once(env):
    b = env.store.create(None).id
    cid = env.add(b, "a.png")
    ext = FakeExtractor()
    q = env.queue(ext)
    q.enqueue(b, cid)
    q.enqueue(b, cid)
    assert q.resume_pending() == 0
    q.start()
    wait_until(lambda: status(env, b, cid) == CaptureStatus.ready)
    other = env.add(b, "z.png")
    q.enqueue(b, other)
    wait_until(lambda: status(env, b, other) == CaptureStatus.ready)
    assert len(ext.calls) == 2


def test_start_resets_interrupted_extractions_and_resumes(env):
    b = env.store.create(None).id
    c1 = env.add(b, "a.png", status=CaptureStatus.extracting)
    c2 = env.add(b, "b.png")
    ready = env.add(b, "c.png", status=CaptureStatus.ready)
    before = env.store.get(b).updated_at
    ext = FakeExtractor(healthy=False)
    q = env.queue(ext)
    q.start()
    wait_until(lambda: all(env.cap(b, c).error for c in (c1, c2)))
    assert status(env, b, c1) == CaptureStatus.pending
    assert status(env, b, c2) == CaptureStatus.pending
    assert status(env, b, ready) == CaptureStatus.ready
    assert env.store.get(b).updated_at == before


def test_resume_pending_counts_only_pending_photo_captures(env):
    b = env.store.create(None).id
    env.add(b, "a.png")
    env.add(b, "b.png", status=CaptureStatus.failed)
    env.store.add_kindle(b, [], None, None, None, None)
    q = env.queue(FakeExtractor())
    assert q.resume_pending() == 1


def test_queue_sets_detected_rotation_once_and_keeps_user_value(env, monkeypatch):
    detected = []

    def fake_detect(path):
        detected.append(path.name)
        return 270

    monkeypatch.setattr(imaging, "detect_rotation", fake_detect)
    b = env.store.create(None).id
    auto = env.add(b, "a.png")
    user = env.add(b, "b.png", rotation=90)
    ext = FakeExtractor()
    q = env.queue(ext)
    q.start()
    q.enqueue(b, auto)
    q.enqueue(b, user)
    wait_until(lambda: len(ext.calls) == 2)
    wait_until(lambda: status(env, b, user) == CaptureStatus.ready)
    assert env.cap(b, auto).rotation == 270
    assert env.cap(b, user).rotation == 90
    assert detected == [env.cap(b, auto).image_file]
    assert [r for _, r in ext.calls] == [270, 90]

    # The user decides the detector was wrong and retries upright: no re-detection.
    env.store.modify(b, lambda batch: _set(batch, auto, rotation=0, status=CaptureStatus.pending))
    q.enqueue(b, auto)
    wait_until(lambda: len(ext.calls) == 3)
    wait_until(lambda: status(env, b, auto) == CaptureStatus.ready)
    assert env.cap(b, auto).rotation == 0
    assert ext.calls[-1][1] == 0
    assert len(detected) == 1


def test_stop_does_not_wait_for_a_hung_extractor(env):
    b = env.store.create(None).id
    cid = env.add(b, "a.png")
    ext = GatedExtractor()
    q = env.queue(ext, timeout_s=180)
    q.start()
    q.enqueue(b, cid)
    assert ext.started.wait(2)
    t0 = time.monotonic()
    q.stop()
    assert time.monotonic() - t0 < 1.5
    ext.release.set()
    # Abandoned mid-flight: left `extracting` for the next start() to reset.
    assert ext.finished.wait(2)
    time.sleep(0.05)
    assert status(env, b, cid) == CaptureStatus.extracting


def test_queue_can_restart_after_stop(env):
    b = env.store.create(None).id
    cid = env.add(b, "a.png")
    q = env.queue(FakeExtractor())
    q.start()
    q.stop()
    q.start()
    q.enqueue(b, cid)
    wait_until(lambda: status(env, b, cid) == CaptureStatus.ready)


def test_fake_extractor_behaviour(tmp_path):
    f = FakeExtractor(error="nope", healthy=False)
    assert f.name == "fake"
    assert f.health().ok is False
    with pytest.raises(ExtractionError, match="nope"):
        f.extract(tmp_path / "x.png", 90)
    assert f.calls == [(tmp_path / "x.png", 90)]
    assert FakeExtractor().extract(tmp_path / "y.png") == ExtractionResult()


@pytest.mark.parametrize("kind", list(ExtractorKind))
def test_build_extractor_not_implemented_until_tasks_8_and_9(kind):
    # Tasks 8/9 replace this with real Ollama/Tesseract construction.
    with pytest.raises(NotImplementedError):
        build_extractor(ExtractorSettings(), kind)
