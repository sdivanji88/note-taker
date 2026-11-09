import threading

import pytest
from push_helpers import (
    _edit_mid_push,
    _mark_pushing,
    add_batch,
    git,
    markers,
    push_env,
    remote_text,
)

from note_taker.models import (
    BatchStatus,
    CaptureStatus,
    Highlight,
    Kind,
)


@pytest.fixture
def env(tmp_path, data_paths, bare_remote):
    return push_env(tmp_path, data_paths, bare_remote)


def test_concurrent_capture_edit_during_push_is_kept(env):
    env.books.create("Dune", None, Kind.fiction)
    batch = add_batch(env, "dune", ("approved", "ready"))

    def user_edits_ready_capture():
        cap = env.store.get(batch.id).captures[1]
        cap.highlights[0].text = "edited by user mid-push"
        env.store.update_capture(batch.id, cap)

    env.events.hooks["committing"] = user_edits_ready_capture
    env.svc.push(batch.id)

    after = env.store.get(batch.id)
    assert after.captures[0].status == CaptureStatus.pushed
    assert after.captures[1].highlights[0].text == "edited by user mid-push"
    assert after.captures[1].status == CaptureStatus.ready


def test_highlight_added_mid_push_keeps_capture_approved(env):
    env.books.create("Dune", None, Kind.fiction)
    batch = add_batch(env, "dune", ("approved",))
    _edit_mid_push(env, batch.id, 0, lambda c: c.highlights.append(Highlight(text="late add")))

    env.svc.push(batch.id)

    after = env.store.get(batch.id)  # not deleted: the capture isn't finished
    assert after.captures[0].status == CaptureStatus.approved
    assert "late add" not in remote_text(env)
    # The next push appends only the new highlight; the first is not duplicated.
    assert env.svc.push(batch.id).highlights_written == 1
    for m in markers(after):
        assert remote_text(env).count(m) == 1


def test_highlight_text_edited_mid_push_keeps_capture_approved(env):
    env.books.create("Dune", None, Kind.fiction)
    batch = add_batch(env, "dune", ("approved",))

    def edit(c):
        c.highlights[0].text = "corrected text"

    _edit_mid_push(env, batch.id, 0, edit)
    env.svc.push(batch.id)

    after = env.store.get(batch.id)
    assert after.captures[0].status == CaptureStatus.approved
    assert after.captures[0].highlights[0].text == "corrected text"


def test_page_changed_mid_push_keeps_capture_approved(env):
    env.books.create("Dune", None, Kind.fiction)
    batch = add_batch(env, "dune", ("approved",))

    def edit(c):
        c.page = 99

    _edit_mid_push(env, batch.id, 0, edit)
    env.svc.push(batch.id)

    after = env.store.get(batch.id)
    assert after.captures[0].status == CaptureStatus.approved
    assert after.captures[0].page == 99


def test_capture_discarded_mid_push_stays_discarded(env):
    env.books.create("Dune", None, Kind.fiction)
    batch = add_batch(env, "dune", ("approved", "approved", "ready"))

    def discard(c):
        c.status = CaptureStatus.discarded

    _edit_mid_push(env, batch.id, 1, discard)
    env.svc.push(batch.id)

    after = env.store.get(batch.id)
    assert [c.status for c in after.captures] == [
        CaptureStatus.pushed, CaptureStatus.discarded, CaptureStatus.ready
    ]


def test_unchanged_capture_resaved_mid_push_is_pushed_and_batch_deleted(env):
    env.books.create("Dune", None, Kind.fiction)
    batch = add_batch(env, "dune", ("approved", "discarded"))
    _edit_mid_push(env, batch.id, 0, lambda c: None)  # a save that changes nothing

    res = env.svc.push(batch.id)

    assert res.batch_deleted is True
    assert not env.paths.batch_dir(batch.id).exists()


def test_recover_marks_pushed_from_remote_markers(env):
    env.books.create("Dune", None, Kind.fiction)
    landed = add_batch(env, "dune", ("approved", "ready"))
    snapshot = env.store.get(landed.id)
    env.svc.push(landed.id)
    _mark_pushing(env, snapshot)  # crashed mid-push after the remote got the commit
    never = add_batch(env, "dune")
    _mark_pushing(env, never)  # crashed before anything reached the remote

    env.svc.recover()

    a = env.store.get(landed.id)
    assert [c.status for c in a.captures] == [CaptureStatus.pushed, CaptureStatus.ready]
    assert a.status == BatchStatus.open
    b = env.store.get(never.id)
    assert b.captures[0].status == CaptureStatus.approved
    assert b.status == BatchStatus.open


def test_recover_deletes_finished_batch(env):
    env.books.create("Dune", None, Kind.fiction)
    batch = add_batch(env, "dune", ("approved", "discarded"))
    snapshot = env.store.get(batch.id)
    env.svc.push(batch.id)
    _mark_pushing(env, snapshot)

    env.svc.recover()

    assert not env.paths.batch_dir(batch.id).exists()


def test_recover_reopens_batch_when_fetch_fails(env, tmp_path):
    batch = add_batch(env, "dune")
    _mark_pushing(env, batch)
    git(env.clone, "remote", "set-url", "origin", str(tmp_path / "nonexistent.git"))

    env.svc.recover()

    after = env.store.get(batch.id)
    assert after.status == BatchStatus.open
    assert after.captures[0].status == CaptureStatus.approved


def test_concurrent_pushes_serialize(env):
    env.books.create("Dune", None, Kind.fiction)
    b1 = add_batch(env, "dune", ("approved", "approved"), on_capture=True)
    b2 = add_batch(env, "dune", ("approved", "approved"))
    results, errors = [], []

    def run(batch_id):
        try:
            results.append(env.svc.push(batch_id))
        except Exception as exc:  # surfaced via the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(b.id,)) for b in (b1, b2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert sorted(r.highlights_written for r in results) == [2, 2]
    text = remote_text(env)
    for m in markers(b1) + markers(b2):
        assert text.count(m) == 1
    assert text.count("title: Dune") == 1
    assert git(env.remote, "rev-list", "--count", "main") == "3"


def _add_capture_after_modify(env, batch_id, when):
    """Simulate an upload landing between a modify and the finished-batch check."""
    real_modify = env.store.modify

    def modify(bid, change, touch=True):
        result = real_modify(bid, change, touch=touch)
        if when(touch):
            env.store.add_kindle(batch_id, [Highlight(text="late upload")], None, 9, None, None)
        return result

    env.store.modify = modify


def test_capture_added_after_push_finish_keeps_batch(env):
    env.books.create("Dune", None, Kind.fiction)
    batch = add_batch(env, "dune", ("approved",))
    _add_capture_after_modify(env, batch.id, when=lambda touch: touch)  # the finish modify

    res = env.svc.push(batch.id)

    assert res.batch_deleted is False
    after = env.store.get(batch.id)
    assert [c.status for c in after.captures] == [CaptureStatus.pushed, CaptureStatus.ready]


def test_capture_added_after_recover_reopen_keeps_batch(env):
    env.books.create("Dune", None, Kind.fiction)
    batch = add_batch(env, "dune", ("approved", "discarded"))
    snapshot = env.store.get(batch.id)
    env.svc.push(batch.id)
    _mark_pushing(env, snapshot)
    _add_capture_after_modify(env, batch.id, when=lambda touch: not touch)

    env.svc.recover()

    after = env.store.get(batch.id)
    assert after.captures[-1].highlights[0].text == "late upload"
