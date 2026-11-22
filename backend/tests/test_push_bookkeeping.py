"""A failure after a successful `git push` must be reported honestly and be safe to retry."""

import logging

import pytest
from api_helpers import H, connect, error_code, kindle, new_batch, repo_path
from push_helpers import add_batch, git, markers, push_env, remote_text

from note_taker.models import BatchStatus, CaptureStatus, Kind
from note_taker.push_service import PushError


@pytest.fixture
def env(tmp_path, data_paths, bare_remote):
    return push_env(tmp_path, data_paths, bare_remote)


def fail_modify_while_pushing(store, monkeypatch, times: int) -> None:
    """Make the first `times` store.modify calls fail while the batch is `pushing`.

    Keyed on batch state rather than call count: in a push, the `pushing` flag is set
    while the batch is open, so the next modifies are exactly finish (and then reopen).
    """
    real = store.modify
    remaining = [times]

    def flaky(batch_id, change, touch=True):
        if remaining[0] and store.get(batch_id).status == BatchStatus.pushing:
            remaining[0] -= 1
            raise OSError("disk full")
        return real(batch_id, change, touch=touch)

    monkeypatch.setattr(store, "modify", flaky)


def _batch(env):
    env.books.create("Dune", None, Kind.fiction)
    # The second capture keeps the batch alive so a retry's effect is observable.
    return add_batch(env, "dune", ("approved", "ready"))


def test_bookkeeping_failure_reopens_the_batch_and_raises(env, monkeypatch):
    batch = _batch(env)
    events = env.events.subscribe(batch.id)
    fail_modify_while_pushing(env.store, monkeypatch, times=1)

    with pytest.raises(PushError) as e:
        env.svc.push(batch.id)

    assert e.value.code == "bookkeeping_failed"
    sha7 = git(env.remote, "rev-parse", "main")[:7]
    assert f"commit {sha7}" in str(e.value)
    assert "Push again" in str(e.value)
    assert remote_text(env) is not None  # the push really happened
    after = env.store.get(batch.id)
    assert after.status == BatchStatus.open
    assert after.captures[0].status == CaptureStatus.approved
    sent = []
    while not events.empty():
        sent.append(events.get_nowait()["data"])
    assert sent[-1] == {"stage": "failed", "code": "bookkeeping_failed"}
    assert {"stage": "done"} not in sent


def test_bookkeeping_failure_is_logged_with_traceback(env, monkeypatch, caplog):
    batch = _batch(env)
    fail_modify_while_pushing(env.store, monkeypatch, times=1)
    with caplog.at_level(logging.ERROR), pytest.raises(PushError):
        env.svc.push(batch.id)
    (rec,) = [r for r in caplog.records if "pushed but bookkeeping failed" in r.getMessage()]
    assert batch.id in rec.getMessage()
    assert git(env.remote, "rev-parse", "main")[:7] in rec.getMessage()
    assert rec.exc_info and "disk full" in str(rec.exc_info[1])


def test_retry_after_bookkeeping_failure_duplicates_nothing_and_marks_pushed(env, monkeypatch):
    batch = _batch(env)
    with monkeypatch.context() as m:
        fail_modify_while_pushing(env.store, m, times=1)
        with pytest.raises(PushError):
            env.svc.push(batch.id)
    remote_head = git(env.remote, "rev-parse", "main")

    result = env.svc.push(batch.id)

    assert result.highlights_written == 0
    assert git(env.remote, "rev-parse", "main") == remote_head  # no second commit
    (written_marker,) = markers(batch)[:1]
    assert remote_text(env).count(written_marker) == 1
    after = env.store.get(batch.id)
    assert after.captures[0].status == CaptureStatus.pushed
    assert after.status == BatchStatus.open


def test_reopen_failure_leaves_pushing_for_recover(env, monkeypatch):
    batch = _batch(env)
    with monkeypatch.context() as m:
        fail_modify_while_pushing(env.store, m, times=2)  # finish, then the reopen
        with pytest.raises(PushError) as e:
            env.svc.push(batch.id)
    assert e.value.code == "bookkeeping_failed"
    assert env.store.get(batch.id).status == BatchStatus.pushing

    env.svc.recover()

    after = env.store.get(batch.id)
    assert after.status == BatchStatus.open
    assert after.captures[0].status == CaptureStatus.pushed


def test_prune_pending_failure_does_not_fail_a_pushed_batch(env, monkeypatch, caplog):
    batch = _batch(env)

    def broken():
        raise OSError("pending_books.json unwritable")

    monkeypatch.setattr(env.books, "prune_pending", broken)
    with caplog.at_level(logging.WARNING):
        result = env.svc.push(batch.id)
    assert result.highlights_written == 1
    assert env.store.get(batch.id).captures[0].status == CaptureStatus.pushed
    assert any("prune" in r.getMessage() for r in caplog.records)


def test_delete_failure_after_finish_does_not_fail_the_push(env, monkeypatch, caplog):
    env.books.create("Dune", None, Kind.fiction)
    batch = add_batch(env, "dune", ("approved",))

    def broken(batch_id, should_delete):
        raise OSError("cannot rmtree")

    monkeypatch.setattr(env.store, "delete_if", broken)
    with caplog.at_level(logging.WARNING):
        result = env.svc.push(batch.id)
    assert result.batch_deleted is False
    assert env.store.get(batch.id).captures[0].status == CaptureStatus.pushed
    assert any("delet" in r.getMessage() for r in caplog.records)


def test_api_bookkeeping_failure_is_500_with_code(client, bare_remote, monkeypatch):
    connect(client, bare_remote)
    client.post("/books", headers=H, json={"title": "Dune", "kind": "fiction"})
    b = new_batch(client, default_book_slug="dune")
    c = kindle(client, b)
    client.patch(f"/captures/{c['id']}", headers=H, json={"status": "approved"})
    fail_modify_while_pushing(client.app.state.services.store, monkeypatch, times=1)

    r = client.post(f"/batches/{b}/push", headers=H)

    assert r.status_code == 500
    assert error_code(r) == "bookkeeping_failed"
    assert "pushed" in r.json()["error"]["message"]
    assert git(repo_path(client), "log", "-1", "--format=%s").startswith("notes:")
