from conftest import dt, make_batch
from note_taker.models import ExtractionResult


def test_page_coerced_from_string():
    assert ExtractionResult(page="163").page == 163
    assert ExtractionResult(page="xvi").page is None


def test_batch_is_finished():
    b = make_batch(statuses=["pushed", "discarded"])
    assert b.is_finished()
    assert not make_batch(statuses=["pushed", "approved"]).is_finished()
    assert not make_batch(statuses=[]).is_finished()


def test_expires_at_counts_from_updated_at():
    b = make_batch(updated_at=dt(2026, 11, 1))
    assert b.expires_at(30) == dt(2026, 12, 1)
