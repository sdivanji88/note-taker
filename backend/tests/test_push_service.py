import subprocess
import threading
from datetime import UTC, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from note_taker.batch_store import BatchStore
from note_taker.books import BookCatalog
from note_taker.events import EventBus
from note_taker.git_publisher import GitPublisher
from note_taker.markdown_writer import append_highlights
from note_taker.models import (
    BatchStatus,
    CaptureStatus,
    Highlight,
    Kind,
    NotesRepoSettings,
    Settings,
)
from note_taker.push_service import PushError, PushService
from conftest import dt


def git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)
    return r.stdout.strip()


def remote_text(env, rel="books/dune.md") -> str | None:
    r = subprocess.run(
        ["git", "-C", str(env.remote), "show", f"main:{rel}"], capture_output=True, text=True
    )
    return r.stdout if r.returncode == 0 else None


class Clock:
    """Strictly increasing time, so a touched updated_at is observably newer."""

    def __init__(self):
        self.t = dt(2026, 11, 1)

    def __call__(self):
        self.t += timedelta(minutes=1)
        return self.t


class RecordingBus(EventBus):
    """Real EventBus that records push stages and can run a hook when a stage is reached.

    Hooks simulate things that happen *during* a push (a user edit from the API thread,
    a lock file appearing) at a precise point without mocking git.
    """

    def __init__(self):
        super().__init__()
        self.stages: list[str] = []
        self.hooks: dict = {}

    def publish(self, batch_id, type, data):
        super().publish(batch_id, type, data)
        if type == "batch.push_progress":
            self.stages.append(data["stage"])
            hook = self.hooks.pop(data["stage"], None)
            if hook:
                hook()


@pytest.fixture
def env(tmp_path, data_paths, bare_remote):
    clone = tmp_path / "clone"
    GitPublisher(clone, str(bare_remote), "main").clone()
    store = BatchStore(data_paths, now=Clock())
    books = BookCatalog(data_paths, lambda: clone, lambda: "books")
    events = RecordingBus()
    settings = Settings(
        notes_repo=NotesRepoSettings(remote_url=str(bare_remote), local_path=str(clone))
    )
    svc = PushService(
        store,
        books,
        lambda: GitPublisher(clone, str(bare_remote), "main"),
        lambda: settings,
        events,
        UTC,
    )
    return SimpleNamespace(
        store=store, books=books, events=events, svc=svc, clone=clone, remote=bare_remote,
        paths=data_paths, settings=settings,
    )


def add_batch(env, slug, statuses=("approved",), on_capture=False):
    """A batch of kindle captures (one highlight each) with the given statuses.

    on_capture puts the slug on each capture instead of the batch default.
    """
    batch = env.store.create(None if on_capture else slug)
    for i, st in enumerate(statuses):
        cap = env.store.add_kindle(
            batch.id,
            [Highlight(text=f"quote {i} of {batch.id}")],
            slug if on_capture else None,
            i + 1,
            None,
            dt(2026, 11, 1, 10, i),
        )
        cap.status = CaptureStatus(st)
        env.store.update_capture(batch.id, cap)
    return env.store.get(batch.id)


def markers(batch):
    return [f"<!-- nt:highlight={h.id} -->" for c in batch.captures for h in c.highlights]


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


def _reject_pushes(remote: Path) -> None:
    hook = remote / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho 'push blocked by test' >&2\nexit 1\n")
    hook.chmod(0o755)


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


def _edit_mid_push(env, batch_id, index, change):
    def hook():
        cap = env.store.get(batch_id).captures[index]
        change(cap)
        env.store.update_capture(batch_id, cap)

    env.events.hooks["committing"] = hook


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


def _mark_pushing(env, batch):
    batch.status = BatchStatus.pushing
    env.store.save(batch, touch=False)


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
