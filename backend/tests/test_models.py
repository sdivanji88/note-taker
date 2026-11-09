from conftest import dt, make_batch
from note_taker.models import ExtractionResult, NotesRepoSettings


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


def test_notes_repo_settings_are_stripped():
    repo = NotesRepoSettings(remote_url=" u ", branch=" b\n", books_dir=" d ", local_path="  ")
    assert (repo.remote_url, repo.branch, repo.books_dir, repo.local_path) == ("u", "b", "d", None)
