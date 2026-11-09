from datetime import UTC

import pytest
from conftest import dt
from push_helpers import (
    _reject_pushes,
    add_batch,
    git,
    markers,
    push_env,
    remote_text,
)

from note_taker.git_publisher import GitPublisher
from note_taker.markdown_writer import append_highlights
from note_taker.models import (
    BatchStatus,
    CaptureStatus,
    Highlight,
    Kind,
)
from note_taker.push_service import PushError, PushService


@pytest.fixture
def env(tmp_path, data_paths, bare_remote):
    return push_env(tmp_path, data_paths, bare_remote)


def test_push_writes_commits_and_deletes_finished_batch(env):
    env.books.create("Dune", "Frank Herbert", Kind.fiction)
    batch = add_batch(env, "dune", ("approved", "approved"))

    res = env.svc.push(batch.id)

    text = remote_text(env)
    assert text.startswith("---\ntitle: Dune\n")
    for m in markers(batch):
        assert text.count(m) == 1
    assert git(env.remote, "log", "-1", "--format=%B", "main") == (
        f"notes: 2 highlights from Dune\n\nNote-Taker-Batch: {batch.id}"
    )
    assert res.commit_sha == git(env.remote, "rev-parse", "main")
    assert res.files_changed == ["books/dune.md"]
    assert res.highlights_written == 2
    assert res.batch_deleted is True
    assert not env.paths.batch_dir(batch.id).exists()
    # The book now lives in the repo, so its pending entry is pruned.
    assert env.books.get("dune").pending is False
    assert env.events.stages == ["started", "pulling", "writing", "committing", "pushing", "done"]


def test_push_keeps_batch_with_unapproved_captures(env):
    env.books.create("Dune", None, Kind.fiction)
    before = add_batch(env, "dune", ("approved", "ready", "discarded"))

    res = env.svc.push(before.id)

    after = env.store.get(before.id)
    assert [c.status for c in after.captures] == [
        CaptureStatus.pushed, CaptureStatus.ready, CaptureStatus.discarded
    ]
    assert after.status == BatchStatus.open
    assert after.updated_at > before.updated_at
    assert res.batch_deleted is False
    assert res.highlights_written == 1
    assert "quote 1" not in remote_text(env)  # the unapproved capture was not written


def test_push_groups_captures_by_book_in_one_commit(env):
    env.books.create("Dune", None, Kind.fiction)
    env.books.create("Atomic Habits", "James Clear", Kind.non_fiction)
    batch = add_batch(env, "dune", ("approved",))
    other = env.store.add_kindle(
        batch.id, [Highlight(text="habits")], "atomic-habits", 3, None, dt(2026, 11, 1, 11)
    )
    other.status = CaptureStatus.approved
    env.store.update_capture(batch.id, other)

    res = env.svc.push(batch.id)

    assert sorted(res.files_changed) == ["books/atomic-habits.md", "books/dune.md"]
    assert "habits" in remote_text(env, "books/atomic-habits.md")
    assert git(env.remote, "log", "-1", "--format=%s", "main") == (
        "notes: 2 highlights from Atomic Habits, Dune"
    )
    assert git(env.remote, "rev-list", "--count", "main") == "2"  # seed + one push commit


def test_push_refuses_dirty_repo(env):
    env.books.create("Dune", None, Kind.fiction)
    before = add_batch(env, "dune")
    (env.clone / "README.md").write_text("local edit\n")

    with pytest.raises(PushError) as e:
        env.svc.push(before.id)

    assert e.value.code == "dirty_repo"
    assert env.store.get(before.id) == before
    assert remote_text(env) is None
    assert (env.clone / "README.md").read_text() == "local edit\n"  # never reset


def test_push_refuses_when_not_cloned(env, tmp_path):
    before = add_batch(env, "dune")
    svc = PushService(
        env.store, env.books,
        lambda: GitPublisher(tmp_path / "missing", str(env.remote), "main"),
        lambda: env.settings, env.events, UTC,
    )
    with pytest.raises(PushError) as e:
        svc.push(before.id)
    assert e.value.code == "not_cloned"
    assert env.store.get(before.id) == before


def test_push_with_no_approved_captures_is_nothing_to_push(env):
    env.books.create("Dune", None, Kind.fiction)
    before = add_batch(env, "dune", ("ready", "pushed"))
    with pytest.raises(PushError) as e:
        env.svc.push(before.id)
    assert e.value.code == "nothing_to_push"
    assert env.store.get(before.id) == before


@pytest.mark.parametrize("slug", ["ghost", None])
def test_unknown_book_writes_nothing(env, slug):
    before = add_batch(env, slug)
    head = git(env.clone, "rev-parse", "HEAD")

    with pytest.raises(PushError) as e:
        env.svc.push(before.id)

    assert e.value.code == "unknown_book"
    assert env.store.get(before.id) == before
    assert not (env.clone / "books").exists()
    assert git(env.clone, "rev-parse", "HEAD") == head


def test_push_failure_rolls_back(env):
    env.books.create("Dune", None, Kind.fiction)
    env.svc.push(add_batch(env, "dune").id)  # an existing book file to restore
    _reject_pushes(env.remote)
    book_file = env.clone / "books" / "dune.md"
    text_before = book_file.read_bytes()
    head_before = git(env.clone, "rev-parse", "HEAD")
    batch = add_batch(env, "dune", ("approved", "approved"))

    with pytest.raises(PushError) as e:
        env.svc.push(batch.id)

    assert e.value.code == "git_failed"
    assert "push blocked by test" in str(e.value)
    assert git(env.clone, "rev-parse", "HEAD") == head_before
    assert book_file.read_bytes() == text_before
    assert git(env.clone, "status", "--porcelain") == ""
    after = env.store.get(batch.id)
    assert [c.status for c in after.captures] == [CaptureStatus.approved] * 2
    assert after.status == BatchStatus.open
    assert env.events.stages[-1] == "failed"


def test_push_failure_when_remote_unreachable(env, tmp_path):
    env.books.create("Dune", None, Kind.fiction)
    git(env.clone, "remote", "set-url", "origin", str(tmp_path / "nonexistent.git"))
    head_before = git(env.clone, "rev-parse", "HEAD")
    batch = add_batch(env, "dune")

    with pytest.raises(PushError) as e:
        env.svc.push(batch.id)

    assert e.value.code == "git_failed"
    assert git(env.clone, "rev-parse", "HEAD") == head_before
    assert not (env.clone / "books" / "dune.md").exists()
    after = env.store.get(batch.id)
    assert after.captures[0].status == CaptureStatus.approved
    assert after.status == BatchStatus.open


def test_rollback_failure_still_reopens_batch(env):
    env.books.create("Dune", None, Kind.fiction)
    batch = add_batch(env, "dune")
    lock = env.clone / ".git" / "index.lock"
    # A stale index.lock (e.g. a crashed editor's git) makes both `git add` and the
    # rollback's `git reset` fail, so the rollback itself raises.
    env.events.hooks["committing"] = lambda: lock.write_text("")

    with pytest.raises(PushError) as e:
        env.svc.push(batch.id)

    assert e.value.code == "git_failed"
    msg = str(e.value)
    assert "index.lock" in msg
    assert "rollback failed" in msg
    after = env.store.get(batch.id)
    assert after.status == BatchStatus.open
    assert after.captures[0].status == CaptureStatus.approved


def test_retry_after_partial_success_does_not_duplicate(env):
    env.books.create("Dune", None, Kind.fiction)
    batch = add_batch(env, "dune", ("approved", "approved"))
    snapshot = env.store.get(batch.id)
    env.svc.push(batch.id)
    head = git(env.remote, "rev-parse", "main")
    # Crash after the push landed but before batch.json recorded it.
    env.store.save(snapshot, touch=False)

    res = env.svc.push(batch.id)

    assert res.highlights_written == 0
    assert res.files_changed == []
    assert res.batch_deleted is True
    assert git(env.remote, "rev-parse", "main") == head
    text = remote_text(env)
    for m in markers(batch):
        assert text.count(m) == 1


def test_push_delivers_stranded_local_commit(env):
    # Crash after the local commit but before `git push`: the next push writes nothing
    # (markers are in the local file) yet must still get that commit to the remote.
    env.books.create("Dune", None, Kind.fiction)
    batch = add_batch(env, "dune")
    pub = GitPublisher(env.clone, str(env.remote), "main")
    path = env.books.book_path("dune")
    cap = batch.captures[0]
    append_highlights(path, env.books.get("dune"), [(cap, cap.highlights[0])], UTC)
    pub.commit([path], "notes: interrupted")

    res = env.svc.push(batch.id)

    assert res.highlights_written == 0
    assert markers(batch)[0] in remote_text(env)
    assert git(env.remote, "rev-parse", "main") == git(env.clone, "rev-parse", "HEAD")
    assert res.batch_deleted is True
