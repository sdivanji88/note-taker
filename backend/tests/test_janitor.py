from datetime import timedelta

import pytest
from conftest import dt

from note_taker.batch_store import BatchStore
from note_taker.janitor import Janitor, JanitorReport, expiring_soon
from note_taker.models import (
    Batch,
    BatchStatus,
    Capture,
    CaptureStatus,
    Settings,
    Source,
)

START = dt(2026, 11, 1)


def _settings(expiry_days=30, warn_days_before=7) -> Settings:
    s = Settings()
    s.batches.expiry_days = expiry_days
    s.batches.warn_days_before = warn_days_before
    return s


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return Clock(START)


@pytest.fixture
def store(data_paths, clock):
    return BatchStore(data_paths, now=clock)


def _janitor(store, clock, settings=None):
    s = settings or _settings()
    return Janitor(store, lambda: s, clock)


def _add_capture(store, batch_id, status):
    batch = store.get(batch_id)
    batch.captures.append(
        Capture(source=Source.photo, captured_at=START, status=CaptureStatus(status))
    )
    store.save(batch, touch=False)


def test_no_action_before_warning_window(store, clock):
    b = store.create(None)
    clock.t = START + timedelta(days=22)
    report = _janitor(store, clock).run()
    assert report == JanitorReport()
    assert store.get(b.id).warned_at is None


def test_warns_at_day_23_without_touching_updated_at(store, clock):
    b = store.create(None)
    clock.t = START + timedelta(days=23)
    report = _janitor(store, clock).run()
    assert report.warned == [b.id] and report.deleted == []
    got = store.get(b.id)
    assert got.warned_at == clock.t
    assert got.updated_at == START


def test_expired_but_never_warned_gets_warned_not_deleted(store, clock):
    b = store.create(None)
    clock.t = START + timedelta(days=40)
    report = _janitor(store, clock).run()
    assert report.warned == [b.id] and report.deleted == []
    assert store.get(b.id).warned_at == clock.t


def test_deletes_24h_after_warning_when_expired(store, clock):
    b = store.create(None)
    clock.t = START + timedelta(days=40)
    j = _janitor(store, clock)
    j.run()
    clock.t += timedelta(hours=23)
    assert j.run() == JanitorReport()
    clock.t += timedelta(hours=1)
    report = j.run()
    assert report.deleted == [b.id] and report.warned == []
    assert store.list() == []


def test_finished_batches_ignored(store, clock):
    b = store.create(None)
    _add_capture(store, b.id, "pushed")
    _add_capture(store, b.id, "discarded")
    clock.t = START + timedelta(days=100)
    assert _janitor(store, clock).run() == JanitorReport()
    assert store.get(b.id).warned_at is None


def test_custom_expiry_days_from_settings(store, clock):
    b = store.create(None)
    s = _settings(expiry_days=10)
    clock.t = START + timedelta(days=2)
    assert _janitor(store, clock, s).run() == JanitorReport()
    clock.t = START + timedelta(days=3)
    assert _janitor(store, clock, s).run().warned == [b.id]


def test_expiring_soon_boundary():
    b = Batch(created_at=START, updated_at=START)
    s = _settings()
    assert not expiring_soon(b, s, START + timedelta(days=23) - timedelta(seconds=1))
    assert expiring_soon(b, s, START + timedelta(days=23))


def test_corrupt_batch_does_not_stop_healthy_expired_one(store, clock, data_paths):
    healthy = store.create(None)
    bad_id = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
    data_paths.batch_file(bad_id).parent.mkdir(parents=True)
    data_paths.batch_file(bad_id).write_text("{not json")
    clock.t = START + timedelta(days=40)
    report = _janitor(store, clock).run()
    assert report.warned == [healthy.id]


def test_list_raising_yields_empty_report(clock):
    class Broken:
        def list_readable(self):
            raise OSError("disk gone")

    j = Janitor(Broken(), lambda: _settings(), clock)
    assert j.run() == JanitorReport()


def test_batch_touched_before_warning_is_left_alone(store, clock):
    b = store.create(None)
    clock.t = START + timedelta(days=40)
    stale = store.get(b.id)
    store.save(store.get(b.id))  # user edit after the janitor listed the batch
    store.list_readable = lambda: iter([stale])
    assert _janitor(store, clock).run() == JanitorReport()
    assert store.get(b.id).warned_at is None


def test_batch_finished_before_warning_is_left_alone(store, clock):
    b = store.create(None)
    _add_capture(store, b.id, "ready")
    clock.t = START + timedelta(days=40)
    stale = store.get(b.id)
    _add_capture(store, b.id, "ready")
    for c in (batch := store.get(b.id)).captures:
        c.status = CaptureStatus.pushed
    store.save(batch, touch=False)
    store.list_readable = lambda: iter([stale])
    assert _janitor(store, clock).run() == JanitorReport()
    assert store.get(b.id).warned_at is None


def test_batch_touched_before_delete_is_left_alone(store, clock):
    b = store.create(None)
    clock.t = START + timedelta(days=40)
    j = _janitor(store, clock)
    j.run()  # warns
    clock.t += timedelta(hours=25)
    stale = store.get(b.id)
    store.save(store.get(b.id))  # user edit moves updated_at to now
    store.list_readable = lambda: iter([stale])
    report = j.run()
    assert report == JanitorReport()
    assert store.get(b.id)


def test_delete_oserror_on_one_batch_does_not_stop_others(store, clock, monkeypatch):
    a = store.create(None)
    c = store.create(None)
    clock.t = START + timedelta(days=40)
    j = _janitor(store, clock)
    j.run()
    clock.t += timedelta(hours=25)
    real = store.delete_if

    def flaky(batch_id, pred):
        if batch_id == a.id:
            raise OSError("boom")
        return real(batch_id, pred)

    monkeypatch.setattr(store, "delete_if", flaky)
    report = j.run()
    assert report.deleted == [c.id]


def _touch_at(store, clock, batch_id, when):
    # A user edit: save() with touch stamps updated_at from the store's clock.
    saved, clock.t = clock.t, when
    store.save(store.get(batch_id))
    clock.t = saved


def test_warning_from_earlier_window_is_not_reused_after_user_edit(store, clock):
    b = store.create(None)
    j = _janitor(store, clock)
    clock.t = START + timedelta(days=23)
    assert j.run().warned == [b.id]
    _touch_at(store, clock, b.id, START + timedelta(days=29))
    clock.t = START + timedelta(days=59, minutes=1)  # just past the new expiry
    report = j.run()
    assert report.warned == [b.id] and report.deleted == []
    assert store.get(b.id).warned_at == clock.t
    clock.t += timedelta(hours=24)
    assert j.run().deleted == [b.id]
    assert store.list() == []


def test_raised_expiry_requires_a_new_warning(store, clock):
    b = store.create(None)
    clock.t = START + timedelta(days=23)
    _janitor(store, clock).run()
    j = _janitor(store, clock, _settings(expiry_days=90))
    clock.t = START + timedelta(days=31)
    assert j.run() == JanitorReport()
    clock.t = START + timedelta(days=83)  # new window start: 90 - 7
    assert j.run().warned == [b.id]
    clock.t += timedelta(days=7)  # at the new expiry, warning is 7 days old
    assert j.run().deleted == [b.id]


def test_stale_warning_between_listing_and_delete_is_not_deleted(store, clock):
    b = store.create(None)
    clock.t = START + timedelta(days=23)
    j = _janitor(store, clock)
    j.run()
    stale = store.get(b.id)
    _touch_at(store, clock, b.id, START + timedelta(days=29))
    clock.t = START + timedelta(days=60)
    store.list_readable = lambda: iter([stale])
    assert j.run() == JanitorReport()
    assert store.get(b.id)


@pytest.mark.parametrize("warned", [False, True])
def test_batch_mid_push_is_neither_warned_nor_deleted(store, clock, warned):
    b = store.create(None)
    _add_capture(store, b.id, "approved")
    batch = store.get(b.id)
    batch.status = BatchStatus.pushing
    batch.warned_at = START + timedelta(days=30) if warned else None
    store.save(batch, touch=False)
    clock.t = START + timedelta(days=40)

    assert _janitor(store, clock).run() == JanitorReport()
    assert store.get(b.id).warned_at == batch.warned_at
