import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import tzinfo
from pathlib import Path
from typing import NoReturn

from note_taker.batch_store import BatchStore
from note_taker.books import BookCatalog, BookNotFound
from note_taker.events import EventBus
from note_taker.git_publisher import GitError, GitPublisher
from note_taker.markdown_writer import append_highlights, existing_marker_ids
from note_taker.models import Batch, BatchStatus, Book, Capture, CaptureStatus, Highlight, Settings

log = logging.getLogger(__name__)

# One clone, one working tree: two pushes interleaving pull/write/commit would
# corrupt each other's rollback, so every push (and recovery) is serialized.
_PUSH_LOCK = threading.Lock()

_Group = tuple[Book, list[tuple[Capture, Highlight]]]


class PushError(Exception):
    """code is one of: dirty_repo, not_cloned, nothing_to_push, unknown_book, git_failed."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


@dataclass
class PushResult:
    commit_sha: str
    files_changed: list[str]
    highlights_written: int
    batch_deleted: bool


def _detail(exc: BaseException) -> str:
    return exc.stderr.strip() if isinstance(exc, GitError) else str(exc)


def _section_key(capture: Capture, batch: Batch) -> tuple:
    # Everything that determines the markdown sections written for a capture
    # (and the file they go to); if any of it changes, the repo copy is stale.
    return (
        tuple((h.id, h.text, h.note) for h in capture.highlights),
        capture.page,
        capture.chapter,
        capture.captured_at,
        capture.book_slug or batch.default_book_slug,
    )


def _set_status(status: BatchStatus) -> Callable[[Batch], None]:
    def change(batch: Batch) -> None:
        batch.status = status

    return change


class PushService:
    """Turns a batch's approved captures into one commit on the notes repo.

    Safe to retry at any point: markdown sections carry highlight markers so a
    re-run never writes a highlight twice, and recover() reconciles batches left
    in `pushing` by a crash against what actually reached the remote.
    """

    def __init__(
        self,
        store: BatchStore,
        books: BookCatalog,
        git_factory: Callable[[], GitPublisher],
        settings: Callable[[], Settings],
        events: EventBus,
        tz: tzinfo,
    ):
        self._store = store
        self._books = books
        self._git_factory = git_factory
        self._settings = settings
        self._events = events
        self._tz = tz

    def push(self, batch_id: str) -> PushResult:
        with _PUSH_LOCK:
            git = self._git_factory()
            books_dir = self._settings().notes_repo.books_dir
            self._check_repo(git, books_dir)
            batch = self._store.get(batch_id)
            approved = [c for c in batch.captures if c.status == CaptureStatus.approved]
            if not approved:
                raise PushError("nothing_to_push", "no approved captures in this batch")
            # Resolved before anything is written, so an unknown book fails cleanly.
            groups = self._group_by_book(batch, approved)

            log.info("push started batch=%s captures=%d", batch_id, len(approved))
            self._store.modify(batch_id, _set_status(BatchStatus.pushing), touch=False)
            self._progress(batch_id, "started")
            try:
                sha, files, written = self._publish(git, batch_id, groups, books_dir)
            except BaseException as exc:
                # Whatever failed, the batch must not be left stuck in `pushing`;
                # captures were never changed, so they are still `approved`.
                self._store.modify(batch_id, _set_status(BatchStatus.open), touch=False)
                code = exc.code if isinstance(exc, PushError) else "error"
                self._progress(batch_id, "failed", code=code)
                raise

            written_as = {c.id: _section_key(c, batch) for c in approved}

            def finish(b: Batch) -> None:
                # Inside the store lock, so comparison and status write are atomic. A capture
                # the user edited, discarded or removed since we read it is not what we wrote:
                # it stays as it is on disk, and a later push appends any new highlight ids
                # (markers keep the already-written ones from being duplicated).
                for c in b.captures:
                    if (
                        c.status == CaptureStatus.approved
                        and written_as.get(c.id) == _section_key(c, b)
                    ):
                        c.status = CaptureStatus.pushed
                b.status = BatchStatus.open

            batch = self._store.modify(batch_id, finish, touch=True)
            self._books.prune_pending()
            deleted = batch.is_finished()
            if deleted:
                self._store.delete(batch_id)
            self._progress(batch_id, "done")
            log.info(
                "push done batch=%s commit=%s highlights=%d files=%d deleted=%s",
                batch_id, sha, written, len(files), deleted,
            )
            return PushResult(
                commit_sha=sha, files_changed=files, highlights_written=written,
                batch_deleted=deleted,
            )

    def recover(self) -> None:
        with _PUSH_LOCK:
            stuck = [b for b in self._store.list() if b.status == BatchStatus.pushing]
            if not stuck:
                return
            git = self._git_factory()
            books_dir = self._settings().notes_repo.books_dir
            try:
                git.fetch()
                fetched = True
            except GitError as exc:
                # Can't see the remote: reopen with captures still approved. A later
                # push is idempotent, so nothing is lost by not marking them here.
                log.warning("recover: fetch failed, reopening without reconciling: %s", _detail(exc))
                fetched = False
            for batch in stuck:
                landed = self._landed_captures(git, batch, books_dir) if fetched else set()
                self._reopen_with_pushed(batch.id, landed)

    def _check_repo(self, git: GitPublisher, books_dir: str) -> None:
        if not git.is_cloned():
            raise PushError("not_cloned", f"notes repo is not cloned at {git.repo_dir}")
        try:
            dirty = git.is_dirty(books_dir)
        except GitError as exc:
            raise PushError("git_failed", _detail(exc)) from exc
        if dirty:
            # Never reset the user's work away; they must commit or discard it themselves.
            raise PushError("dirty_repo", "notes repo has uncommitted changes")

    def _group_by_book(self, batch: Batch, captures: list[Capture]) -> dict[str, _Group]:
        groups: dict[str, _Group] = {}
        for c in captures:
            slug = c.book_slug or batch.default_book_slug
            if slug not in groups:
                try:
                    if not slug:
                        raise BookNotFound(slug)
                    book = self._books.get(slug)
                except BookNotFound:
                    raise PushError(
                        "unknown_book", f"capture {c.id} has no known book ({slug!r})"
                    ) from None
                groups[slug] = (book, [])
            groups[slug][1].extend((c, h) for h in c.highlights)
        return groups

    def _publish(
        self, git: GitPublisher, batch_id: str, groups: dict[str, _Group], books_dir: str
    ) -> tuple[str, list[str], int]:
        pre: str | None = None
        attempted: list[Path] = []
        try:
            pre = git.head()
            self._progress(batch_id, "pulling")
            git.pull_rebase()
            pre = git.head()

            self._progress(batch_id, "writing")
            changed: list[Path] = []
            files: list[str] = []
            titles: list[str] = []
            written = 0
            for slug, (book, items) in groups.items():
                path = self._books.book_path(slug)
                # Recorded before writing so a write that dies halfway is still rolled back.
                attempted.append(path)
                ids = append_highlights(path, book, items, self._tz)
                if ids:
                    changed.append(path)
                    files.append(Path(books_dir, f"{slug}.md").as_posix())
                    titles.append(book.title)
                    written += len(ids)

            if changed:
                self._progress(batch_id, "committing")
                titles.sort(key=str.lower)
                git.commit(
                    changed,
                    f"notes: {written} highlights from {', '.join(titles)}\n\n"
                    f"Note-Taker-Batch: {batch_id}",
                )
            # Even with nothing new written: a crash between commit and push leaves a
            # local commit whose markers make the retry write nothing, and it still
            # has to reach the remote. Pushing an up-to-date HEAD is a no-op.
            self._progress(batch_id, "pushing")
            git.push()
            return git.head(), files, written
        except Exception as exc:
            self._rollback(git, batch_id, pre, attempted, exc)

    def _rollback(
        self, git: GitPublisher, batch_id: str, pre: str | None, attempted: list[Path],
        exc: Exception,
    ) -> NoReturn:
        detail = _detail(exc)
        if pre is not None:
            try:
                git.rollback(pre, attempted)
            except Exception as rb_exc:
                # Report both: the user needs the original cause and to know the clone
                # may need manual attention before the next push.
                log.error("rollback failed batch=%s: %s", batch_id, _detail(rb_exc))
                detail = f"{detail}\nrollback failed: {_detail(rb_exc)}"
        log.error("push failed batch=%s: %s", batch_id, detail)
        if isinstance(exc, GitError):
            raise PushError("git_failed", detail) from exc
        raise exc

    def _landed_captures(self, git: GitPublisher, batch: Batch, books_dir: str) -> set[str]:
        remote_markers: dict[str, set[str]] = {}
        landed = set()
        for c in batch.captures:
            slug = c.book_slug or batch.default_book_slug
            if c.status != CaptureStatus.approved or not slug or not c.highlights:
                continue
            if slug not in remote_markers:
                text = git.remote_file(Path(books_dir, f"{slug}.md").as_posix())
                remote_markers[slug] = existing_marker_ids(text) if text else set()
            if all(h.id in remote_markers[slug] for h in c.highlights):
                landed.add(c.id)
        return landed

    def _reopen_with_pushed(self, batch_id: str, landed: set[str]) -> None:
        def change(b: Batch) -> None:
            for c in b.captures:
                if c.id in landed:
                    c.status = CaptureStatus.pushed
            b.status = BatchStatus.open

        # touch=False: recovery is background work and must not extend expiry.
        batch = self._store.modify(batch_id, change, touch=False)
        deleted = batch.is_finished()
        if deleted:
            self._store.delete(batch_id)
        log.info(
            "recovered batch=%s pushed=%d deleted=%s", batch_id, len(landed), deleted
        )

    def _progress(self, batch_id: str, stage: str, **extra) -> None:
        self._events.publish(batch_id, "batch.push_progress", {"stage": stage, **extra})
