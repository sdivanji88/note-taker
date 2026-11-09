import logging
import queue
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass

from note_taker import imaging
from note_taker.batch_store import BatchNotFound, BatchStore
from note_taker.events import EventBus
from note_taker.extractors.base import ExtractionError, Extractor
from note_taker.models import Batch, Capture, CaptureStatus, ExtractionResult, ExtractorKind, Highlight, Source

log = logging.getLogger(__name__)

# How often an idle or waiting worker checks whether it is being stopped.
_STOP_POLL_S = 0.05
_JOIN_TIMEOUT_S = 1.0


@dataclass(frozen=True)
class _Job:
    batch_id: str
    capture_id: str
    kind: ExtractorKind | None


class _Stopped(Exception):
    pass


def _find(batch: Batch, capture_id: str) -> Capture | None:
    return next((c for c in batch.captures if c.id == capture_id), None)


class ExtractionQueue:
    """Background FIFO of photo captures waiting for an extractor.

    Concurrency rules:
    - The store is the only shared state with the API thread, and every write goes through
      `BatchStore.modify` with `touch=False`, so user edits are never overwritten by a stale
      copy and background work never resets batch expiry.
    - Each extraction run claims its capture with a private token, set in `_claims` in the
      same locked `modify` that moves the capture `pending` -> `extracting`. Every later write
      by that run (rotation guess, ready, failed) happens in a locked `modify` that requires
      the capture to still exist, still be `extracting`, and still be claimed by that token.
      So an outcome is dropped if the user discarded, removed or re-queued the capture
      meanwhile, and an older run can never overwrite a newer one: neither a second worker
      (concurrency > 1) nor a later start() after stop().
    - A run whose queue has been stopped never claims anything, so a worker that outlived
      stop()'s bounded join can't start work for a run that is over.
    - Claims are dropped when their run ends (whatever the outcome), when start() resets an
      interrupted capture, and on stop(), so `_claims` holds at most one entry per worker
      plus abandoned runs until the next stop().
    - Extractor threads never touch the store; only worker threads do. So an extraction that
      outlives its timeout can finish whenever it likes without effect.
    """

    def __init__(
        self,
        store: BatchStore,
        extractor_provider: Callable[[ExtractorKind | None], Extractor],
        events: EventBus,
        concurrency: int = 1,
        timeout_s: float = 180,
        health_interval_s: float = 30,
    ):
        self._store = store
        self._provider = extractor_provider
        self._events = events
        self._concurrency = max(1, concurrency)
        self._timeout_s = timeout_s
        self._health_interval_s = health_interval_s
        self._jobs: queue.Queue[_Job] = queue.Queue()
        self._lock = threading.Lock()
        # Capture ids waiting in _jobs, so resume_pending and repeated enqueues don't
        # extract the same photo twice.
        self._queued: set[str] = set()
        # Captures already given one rotation guess. In memory only: after a restart a
        # capture still at rotation 0 gets one more guess, which is harmless.
        self._rotation_checked: set[str] = set()
        # capture id -> token of the run that currently owns it (see class docstring).
        self._claims: dict[str, object] = {}
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._executors: list[ThreadPoolExecutor] = []

    def start(self) -> None:
        with self._lock:
            if self._threads:
                return
            # A fresh event per run: a worker from a previous run that outlived stop()'s
            # bounded join keeps seeing its own (set) event and exits instead of reviving.
            stop = self._stop = threading.Event()
        reset = self._reset_interrupted()
        resumed = self.resume_pending()
        log.info("extraction queue started reset=%d resumed=%d", reset, resumed)
        threads = [
            threading.Thread(target=self._work, args=(stop,), name=f"extract-{i}", daemon=True)
            for i in range(self._concurrency)
        ]
        threads.append(
            threading.Thread(target=self._health_loop, args=(stop,), name="extract-health", daemon=True)
        )
        with self._lock:
            self._threads = threads
        for t in threads:
            t.start()

    def stop(self) -> None:
        # Bounded: a hung extractor can't be killed, so its capture is left `extracting`
        # and the next start() puts it back to `pending`.
        with self._lock:
            threads, self._threads = self._threads, []
            executors, self._executors = self._executors, []
            stop = self._stop
            # Abandoned runs lose ownership now, so nothing they finish later can land.
            self._claims.clear()
        if not threads:
            return
        stop.set()
        for t in threads:
            t.join(_JOIN_TIMEOUT_S)
        for ex in executors:
            ex.shutdown(wait=False, cancel_futures=True)
        log.info("extraction queue stopped")

    def enqueue(self, batch_id: str, capture_id: str, kind: ExtractorKind | None = None) -> None:
        with self._lock:
            if capture_id in self._queued:
                return
            self._queued.add(capture_id)
        self._jobs.put(_Job(batch_id, capture_id, kind))

    def resume_pending(self) -> int:
        """Queue every pending photo capture not already queued; returns how many were added."""
        added = 0
        for batch in self._store.list():
            for c in batch.captures:
                if c.status is CaptureStatus.pending and c.image_file:
                    with self._lock:
                        if c.id in self._queued:
                            continue
                        self._queued.add(c.id)
                    self._jobs.put(_Job(batch.id, c.id, None))
                    added += 1
        return added

    # --- worker side -------------------------------------------------------------

    def _reset_interrupted(self) -> int:
        count = 0
        for batch in self._store.list():
            if not any(c.status is CaptureStatus.extracting for c in batch.captures):
                continue

            def reset(b: Batch) -> None:
                nonlocal count
                for c in b.captures:
                    if c.status is CaptureStatus.extracting:
                        c.status = CaptureStatus.pending
                        self._release(c.id)
                        count += 1

            try:
                self._store.modify(batch.id, reset, touch=False)
            except BatchNotFound:
                pass
        return count

    def _health_loop(self, stop: threading.Event) -> None:
        # Unhealthy jobs are dropped back to `pending`; this is what picks them up again
        # once Ollama comes up, without the user having to press retry. With nothing
        # pending a pass is just a directory scan; each queued job re-checks health itself.
        while not stop.wait(self._health_interval_s):
            try:
                self.resume_pending()
            except Exception:  # noqa: BLE001 - the loop must outlive a bad read
                log.exception("health loop pass failed")

    def _work(self, stop: threading.Event) -> None:
        executor = self._new_executor()
        while not stop.is_set():
            try:
                # Timed so stop() is noticed without sentinels that a later start() could eat.
                job = self._jobs.get(timeout=_STOP_POLL_S)
            except queue.Empty:
                continue
            with self._lock:
                self._queued.discard(job.capture_id)
            try:
                executor = self._run(job, executor, stop)
            except _Stopped:
                break
            except Exception:  # noqa: BLE001 - one bad job must not kill the worker
                log.exception("extraction job crashed batch=%s capture=%s", job.batch_id, job.capture_id)

    def _new_executor(self) -> ThreadPoolExecutor:
        ex = ThreadPoolExecutor(max_workers=1, thread_name_prefix="extractor")
        with self._lock:
            self._executors.append(ex)
        return ex

    def _abandon(self, executor: ThreadPoolExecutor) -> ThreadPoolExecutor:
        # The hung call keeps its thread; later jobs get a fresh one so their timeout
        # clock isn't eaten by waiting behind it.
        executor.shutdown(wait=False, cancel_futures=True)
        with self._lock:
            if executor in self._executors:
                self._executors.remove(executor)
        return self._new_executor()

    def _run(self, job: _Job, executor: ThreadPoolExecutor, stop: threading.Event) -> ThreadPoolExecutor:
        capture = self._read(job)
        if capture is None or capture.status is not CaptureStatus.pending or not capture.image_file:
            return executor

        try:
            extractor = self._provider(job.kind)
            health = extractor.health()
            ok, detail = health.ok, health.detail
        except Exception as exc:  # noqa: BLE001 - a broken provider is just "unavailable"
            extractor, ok, detail = None, False, str(exc) or type(exc).__name__
        if not ok:
            log.warning("extractor unavailable capture=%s: %s", job.capture_id, detail)
            message = f"extractor unavailable: {detail}"
            if self._modify_if(job, lambda c: c.status is CaptureStatus.pending, _set_error(message)):
                self._publish_status(job, CaptureStatus.pending, message)
            return executor

        claimed = self._claim(job, stop)
        if claimed is None:
            return executor
        capture, token = claimed
        try:
            return self._extract(job, executor, stop, extractor, capture, token)
        finally:
            # Whatever happened, this run is over; a newer run's claim is left alone.
            self._release(job.capture_id, token)

    def _extract(
        self,
        job: _Job,
        executor: ThreadPoolExecutor,
        stop: threading.Event,
        extractor: Extractor,
        capture: Capture,
        token: object,
    ) -> ThreadPoolExecutor:
        self._publish_status(job, CaptureStatus.extracting, None)

        rotation = self._rotation_for(job, capture, token)
        if rotation is None:
            return executor
        photo = self._store.photo_path(job.batch_id, capture)

        started = time.monotonic()
        future = executor.submit(extractor.extract, photo, rotation)
        try:
            result = self._await(future, stop)
        except TimeoutError:
            executor = self._abandon(executor)
            self._fail(job, token, self._timeout_message(self._timeout_s))
            return executor
        except ExtractionError as exc:
            self._fail(job, token, str(exc))
            return executor
        except _Stopped:
            raise
        except Exception as exc:  # noqa: BLE001 - surface any extractor bug on the capture
            log.exception("extractor crashed capture=%s", job.capture_id)
            self._fail(job, token, f"extraction crashed: {exc}")
            return executor

        applied = self._apply_owned(job, token, _set_ready(result, extractor.name))
        if applied:
            log.info(
                "extracted capture=%s highlights=%d extractor=%s elapsed=%.1fs",
                job.capture_id, len(result.highlights), extractor.name, time.monotonic() - started,
            )
            self._publish_status(job, CaptureStatus.ready, None)
            self._events.publish(
                job.batch_id,
                "capture.extracted",
                {"capture_id": job.capture_id, "capture": applied.model_dump(mode="json")},
            )
        return executor

    def _await(self, future: Future, stop: threading.Event) -> ExtractionResult:
        # Waits in short slices so stop() can interrupt; the extractor's own exception
        # (even a TimeoutError of its own) is re-raised only via future.result().
        deadline = time.monotonic() + self._timeout_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            done, _ = wait([future], timeout=min(_STOP_POLL_S, remaining))
            if done:
                try:
                    return future.result()
                except TimeoutError as exc:
                    raise ExtractionError(str(exc) or "extractor timed out") from exc
            if stop.is_set():
                raise _Stopped

    def _rotation_for(self, job: _Job, capture: Capture, token: object) -> int | None:
        """The rotation to extract with, guessing it once for a photo nobody has turned."""
        if capture.rotation != 0 or capture.id in self._rotation_checked or capture.source is not Source.photo:
            return capture.rotation
        self._rotation_checked.add(capture.id)
        guess = imaging.detect_rotation(self._store.photo_path(job.batch_id, capture))

        def store_guess(c: Capture) -> None:
            # The user may have turned it by hand while we were guessing.
            if c.rotation == 0:
                c.rotation = guess

        applied = self._apply_owned(job, token, store_guess)
        return applied.rotation if applied else None

    def _fail(self, job: _Job, token: object, message: str) -> None:
        log.warning("extraction failed capture=%s: %s", job.capture_id, message)

        def set_failed(c: Capture) -> None:
            c.status = CaptureStatus.failed
            c.error = message

        if self._apply_owned(job, token, set_failed):
            self._publish_status(job, CaptureStatus.failed, message)

    @staticmethod
    def _timeout_message(timeout_s: float) -> str:
        return f"timed out after {timeout_s:g}s"

    def _read(self, job: _Job) -> Capture | None:
        try:
            return _find(self._store.get(job.batch_id), job.capture_id)
        except BatchNotFound:
            return None

    def _claim(self, job: _Job, stop: threading.Event) -> tuple[Capture, object] | None:
        """Move the capture to `extracting` and record this run as its owner, atomically."""
        token = object()

        def claim(c: Capture) -> None:
            _set_extracting(c)
            with self._lock:
                self._claims[c.id] = token

        # The stop check sits inside the locked modify so it can't interleave with
        # start()'s reset of interrupted captures.
        claimed = self._modify_if(
            job, lambda c: c.status is CaptureStatus.pending and not stop.is_set(), claim
        )
        if claimed is None:
            reason = "queue stopped" if stop.is_set() else "no longer pending"
            log.info("not claiming capture=%s (%s)", job.capture_id, reason)
            return None
        return claimed, token

    def _apply_owned(self, job: _Job, token: object, change: Callable[[Capture], None]) -> Capture | None:
        """Apply a run's outcome only if that run still owns the `extracting` capture."""
        updated = self._modify_if(
            job,
            lambda c: c.status is CaptureStatus.extracting and self._owns(c.id, token),
            change,
        )
        if updated is None:
            log.info("dropping stale outcome capture=%s (run no longer owns it)", job.capture_id)
        return updated

    def _modify_if(
        self, job: _Job, allowed: Callable[[Capture], bool], change: Callable[[Capture], None]
    ) -> Capture | None:
        """Apply `change` under the store lock if the capture exists and `allowed` holds.

        Returns the updated capture, or None when nothing was written.
        """
        updated: Capture | None = None

        def guarded(batch: Batch) -> None:
            nonlocal updated
            c = _find(batch, job.capture_id)
            if c is not None and allowed(c):
                change(c)
                updated = c

        try:
            self._store.modify(job.batch_id, guarded, touch=False)
        except BatchNotFound:
            return None
        return updated

    def _owns(self, capture_id: str, token: object) -> bool:
        with self._lock:
            return self._claims.get(capture_id) is token

    def _release(self, capture_id: str, token: object | None = None) -> None:
        # With a token, only that run's claim is dropped, never a newer run's.
        with self._lock:
            if token is None or self._claims.get(capture_id) is token:
                self._claims.pop(capture_id, None)

    def _publish_status(self, job: _Job, status: CaptureStatus, error: str | None) -> None:
        self._events.publish(
            job.batch_id,
            "capture.status_changed",
            {"capture_id": job.capture_id, "status": status.value, "error": error},
        )


def _set_error(message: str) -> Callable[[Capture], None]:
    def change(c: Capture) -> None:
        c.error = message

    return change


def _set_extracting(c: Capture) -> None:
    c.status = CaptureStatus.extracting
    c.error = None


def _set_ready(result: ExtractionResult, extractor_name: str) -> Callable[[Capture], None]:
    def change(c: Capture) -> None:
        c.status = CaptureStatus.ready
        c.error = None
        c.extractor_used = extractor_name
        # Margin notes can't be tied to a passage, so the single note rides on the first
        # highlight and the user moves it if needed.
        c.highlights = [
            Highlight(text=h.text, note=result.note if i == 0 else None)
            for i, h in enumerate(result.highlights)
        ]
        # The user may have typed these while we worked; their values win.
        if c.page is None:
            c.page = result.page
        if c.chapter is None:
            c.chapter = result.chapter

    return change
