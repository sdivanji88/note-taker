import logging

import pytest
from queue_helpers import (
    Blocking,
    GatedExtractor,
    _set,
    queue_env,
    status,
    wait_until,
)

from note_taker.extraction_queue import ExtractionQueue
from note_taker.models import (
    CaptureStatus,
    ExtractorKind,
)

# Rotation detection is exercised explicitly; elsewhere it must be inert and fast.
pytestmark = pytest.mark.usefixtures("no_osd")


@pytest.fixture
def env(data_paths, make_image):
    yield from queue_env(data_paths, make_image)


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


def test_concurrent_retry_applies_only_the_newer_run(env, caplog):
    caplog.set_level(logging.INFO, logger="note_taker.extraction_queue")
    b = env.store.create(None).id
    cid = env.add(b, "a.png", rotation=180)
    old, new = Blocking("old"), Blocking("new")
    q = ExtractionQueue(
        env.store,
        lambda kind: new if kind is ExtractorKind.tesseract else old,
        env.bus,
        concurrency=2,
        health_interval_s=60,
    )
    try:
        q.enqueue(b, cid)
        q.start()
        assert old.started.wait(2)
        # The user turns the photo and retries with the other extractor mid-extraction.
        env.store.modify(
            b, lambda batch: _set(batch, cid, status=CaptureStatus.pending, rotation=90)
        )
        q.enqueue(b, cid, ExtractorKind.tesseract)
        assert new.started.wait(2)
        old.release.set()
        assert old.finished.wait(2)
        # The old run must give up while the new run still owns the capture.
        wait_until(lambda: "dropping stale outcome" in caplog.text)
        assert status(env, b, cid) == CaptureStatus.extracting
        new.release.set()
        wait_until(lambda: status(env, b, cid) == CaptureStatus.ready)
        c = env.cap(b, cid)
        assert ([h.text for h in c.highlights], c.extractor_used, c.rotation) == (["new"], "new", 90)
        assert (old.rotations, new.rotations) == ([180], [90])
    finally:
        old.release.set()
        new.release.set()
        q.stop()


def test_leftover_worker_from_stopped_run_cannot_claim(env, caplog):
    caplog.set_level(logging.INFO, logger="note_taker.extraction_queue")
    b = env.store.create(None).id
    cid = env.add(b, "a.png")
    old, new = Blocking("old", block_health=True), Blocking("new", block_health=True)
    current = {"ext": old}
    q = ExtractionQueue(env.store, lambda kind: current["ext"], env.bus, health_interval_s=60)
    try:
        q.enqueue(b, cid)
        q.start()
        assert old.health_started.wait(2)
        q.stop()  # the worker is stuck in health(); the bounded join gives up on it
        current["ext"] = new
        q.start()
        assert new.health_started.wait(2)
        old.release.set()
        # The leftover worker must not claim the capture for a run that has ended.
        wait_until(
            lambda: "not claiming" in caplog.text
            or status(env, b, cid) != CaptureStatus.pending
            or old.started.is_set()
        )
        assert (status(env, b, cid), old.started.is_set()) == (CaptureStatus.pending, False)
        new.release.set()
        wait_until(lambda: status(env, b, cid) == CaptureStatus.ready)
        assert [h.text for h in env.cap(b, cid).highlights] == ["new"]
    finally:
        old.release.set()
        new.release.set()
        q.stop()


def test_claims_are_released_after_every_outcome(env):
    b = env.store.create(None).id
    ok, bad, gone = env.add(b, "a.png"), env.add(b, "b.png"), env.add(b, "c.png")
    ext = GatedExtractor()
    q = env.queue(ext, timeout_s=0.3)
    q.start()
    q.enqueue(b, gone)
    assert ext.started.wait(2)
    env.store.modify(b, lambda batch: _set(batch, gone, status=CaptureStatus.discarded))
    ext.release.set()
    q.enqueue(b, ok)
    wait_until(lambda: status(env, b, ok) == CaptureStatus.ready)
    ext.result = None
    env.store.modify(b, lambda batch: _set(batch, bad, status=CaptureStatus.pending))
    q.enqueue(b, bad)
    wait_until(lambda: status(env, b, bad) == CaptureStatus.ready)
    # White-box: the ownership map must not grow with every capture ever extracted.
    assert q._claims == {}
