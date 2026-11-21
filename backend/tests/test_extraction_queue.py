import time

import pytest
from queue_helpers import GatedExtractor, _drain, queue_env, status, wait_until

from note_taker.extraction_queue import ExtractionQueue
from note_taker.extractors.fake import FakeExtractor
from note_taker.models import (
    CaptureStatus,
    ExtractedHighlight,
    ExtractionResult,
    ExtractorKind,
)

# Rotation detection is exercised explicitly; elsewhere it must be inert and fast.
pytestmark = pytest.mark.usefixtures("no_osd")


@pytest.fixture
def env(data_paths, make_image):
    yield from queue_env(data_paths, make_image)


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
