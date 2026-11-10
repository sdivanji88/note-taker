"""Shared helpers for the push service test modules."""

import subprocess
from datetime import UTC, timedelta
from pathlib import Path
from types import SimpleNamespace

from conftest import dt

from note_taker.batch_store import BatchStore
from note_taker.books import BookCatalog
from note_taker.events import EventBus
from note_taker.git_publisher import GitPublisher
from note_taker.models import (
    BatchStatus,
    CaptureStatus,
    Highlight,
    NotesRepoSettings,
    Settings,
)
from note_taker.push_service import PushService


def git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)
    return r.stdout.strip()


def remote_text(env, rel="books/dune.md") -> str | None:
    r = subprocess.run(
        ["git", "-C", str(env.remote), "show", f"main:{rel}"],
        check=False, capture_output=True, text=True,
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


def push_env(tmp_path, data_paths, bare_remote):
    """Body of each module's `env` fixture: a fresh clone of bare_remote and a PushService on it."""
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


def _reject_pushes(remote: Path) -> None:
    hook = remote / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho 'push blocked by test' >&2\nexit 1\n")
    hook.chmod(0o755)


def _edit_mid_push(env, batch_id, index, change):
    def hook():
        cap = env.store.get(batch_id).captures[index]
        change(cap)
        env.store.update_capture(batch_id, cap)

    env.events.hooks["committing"] = hook


def _mark_pushing(env, batch):
    batch.status = BatchStatus.pushing
    env.store.save(batch, touch=False)
