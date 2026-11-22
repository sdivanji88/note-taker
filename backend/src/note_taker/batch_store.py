# Deferred annotations: the `list()` method would otherwise shadow the builtin in later signatures.
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from ulid import ULID

from note_taker import imaging
from note_taker.jsonio import read_json, write_json_atomic
from note_taker.models import Batch, Capture, CaptureStatus, Highlight, Source
from note_taker.paths import DataPaths

log = logging.getLogger(__name__)

# Long edge of the previews the UI shows: plenty for reading a page on screen, a fraction
# of a 12 MP phone photo's decode and transfer cost.
_PREVIEW_MAX_EDGE = 2000


class BatchNotFound(Exception):
    pass


class UnsupportedImage(Exception):
    pass


class DuplicatePhoto(Exception):
    pass


def utcnow() -> datetime:
    return datetime.now(UTC)


def _is_valid_id(batch_id: str) -> bool:
    # Ids come from URLs and become directory names (and rmtree targets), so only
    # canonical ULIDs, which we mint ourselves, may reach the filesystem.
    try:
        return str(ULID.from_str(batch_id)) == batch_id
    except (ValueError, TypeError):
        return False


def _sniff_extension(data: bytes) -> str | None:
    # Magic bytes, not the filename: uploads come from drag-and-drop with arbitrary names.
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    return None


# One process-wide lock: the API thread pool, extraction worker and janitor all
# read-modify-write batch.json, and a single user never needs finer granularity.
_LOCK = threading.RLock()


class BatchStore:
    def __init__(self, paths: DataPaths, now: Callable[[], datetime] = utcnow):
        self._paths = paths
        self._now = now

    def create(self, default_book_slug: str | None) -> Batch:
        with _LOCK:
            when = self._now()
            batch = Batch(default_book_slug=default_book_slug, created_at=when, updated_at=when)
            self._write(batch)
            return batch

    def get(self, batch_id: str) -> Batch:
        # Every public method that takes a batch_id reaches the disk through here
        # or through delete/photo_path, so this is the single validation point.
        if not _is_valid_id(batch_id):
            raise BatchNotFound(batch_id)
        data = read_json(self._paths.batch_file(batch_id))
        if data is None:
            raise BatchNotFound(batch_id)
        return Batch.model_validate(data)

    def list(self) -> list[Batch]:
        """Every readable batch, oldest first.

        An unreadable batch.json is skipped (and logged) rather than raised: callers like
        the batch list, startup and the janitor need every other batch, and a
        traceback per call would flood the log for one bad file.
        """
        with _LOCK:
            root = self._paths.batches_dir
            if not root.exists():
                return []
            batches = []
            for d in root.iterdir():
                try:
                    data = read_json(d / "batch.json")
                    if data is not None:
                        batches.append(Batch.model_validate(data))
                except ValueError as exc:  # JSON, UnicodeDecode and pydantic validation errors
                    log.warning("skipping unreadable batch %s: %s", d.name, exc)
        return sorted(batches, key=lambda b: b.created_at)

    def save(self, batch: Batch, touch: bool = True) -> Batch:
        # Background work (extraction) passes touch=False so it doesn't reset expiry.
        with _LOCK:
            if touch:
                batch.updated_at = self._now()
            self._write(batch)
            return batch

    def modify(self, batch_id: str, change: Callable[[Batch], None], touch: bool = True) -> Batch:
        # Re-read and write under the lock so a long-running caller (a push) that only
        # owns some fields never overwrites edits made since it last read the batch.
        with _LOCK:
            batch = self.get(batch_id)
            change(batch)
            return self.save(batch, touch=touch)

    def add_photo(self, batch_id: str, filename: str, data: bytes) -> Capture:
        ext = _sniff_extension(data)
        if ext is None:
            raise UnsupportedImage(filename)
        sha = hashlib.sha256(data).hexdigest()
        with _LOCK:
            batch = self.get(batch_id)
            if any(c.image_sha256 == sha for c in batch.captures):
                raise DuplicatePhoto(filename)
            uploaded = self._now()
            # Placeholder until the photo is on disk: EXIF is read from the file.
            capture = Capture(source=Source.photo, image_sha256=sha, captured_at=uploaded)
            capture.image_file = f"{capture.id}.{ext}"
            photo = self._paths.photos_dir(batch_id) / capture.image_file
            photo.parent.mkdir(parents=True, exist_ok=True)
            photo.write_bytes(data)
            try:
                capture.captured_at = imaging.captured_at(photo, uploaded)
                batch.captures.append(capture)
                self.save(batch)
            except BaseException:
                photo.unlink(missing_ok=True)
                raise
            return capture

    def add_kindle(
        self,
        batch_id: str,
        highlights: list[Highlight],
        book_slug: str | None,
        page: int | None,
        chapter: str | None,
        captured_at: datetime | None,
    ) -> Capture:
        with _LOCK:
            batch = self.get(batch_id)
            capture = Capture(
                source=Source.kindle,
                book_slug=book_slug,
                page=page,
                chapter=chapter,
                captured_at=captured_at or self._now(),
                status=CaptureStatus.ready,
                highlights=highlights,
            )
            batch.captures.append(capture)
            self.save(batch)
            return capture

    def update_capture(self, batch_id: str, capture: Capture) -> Batch:
        with _LOCK:
            batch = self.get(batch_id)
            batch.captures = [capture if c.id == capture.id else c for c in batch.captures]
            return self.save(batch)

    def remove_capture(self, batch_id: str, capture_id: str) -> None:
        with _LOCK:
            batch = self.get(batch_id)
            for c in batch.captures:
                if c.id == capture_id:
                    self.drop_photo(batch_id, c)
            batch.captures = [c for c in batch.captures if c.id != capture_id]
            self.save(batch)

    def find_capture(self, capture_id: str) -> tuple[Batch, Capture]:
        for batch in self.list():
            for c in batch.captures:
                if c.id == capture_id:
                    return batch, c
        raise BatchNotFound(capture_id)

    def photo_path(self, batch_id: str, capture: Capture) -> Path:
        assert capture.image_file, "kindle captures have no photo"
        if not _is_valid_id(batch_id):
            raise BatchNotFound(batch_id)
        return self._paths.photos_dir(batch_id) / capture.image_file

    def preview_jpeg(self, batch_id: str, capture: Capture) -> bytes:
        """Upright JPEG of the capture's photo, long edge <= 2000 px, cached on disk.

        Generated via `imaging.downscaled_jpeg_bytes`, so EXIF orientation and the
        capture's own rotation are applied exactly as for extraction. The cache lives
        in the batch folder (freed with the batch) and is keyed by rotation, so a turn
        simply misses. Raises FileNotFoundError if the photo is missing.
        """
        cached = self._paths.preview_file(batch_id, capture.id, capture.rotation)
        try:
            return cached.read_bytes()
        except FileNotFoundError:
            pass
        photo = self.photo_path(batch_id, capture)
        # Decoded outside _LOCK: a 12 MP decode would stall every batch.json write.
        data = imaging.downscaled_jpeg_bytes(photo, _PREVIEW_MAX_EDGE, capture.rotation)
        self._cache_preview(cached, photo, capture.id, data)
        return data

    def _cache_preview(self, target: Path, photo: Path, capture_id: str, data: bytes) -> None:
        # Best effort: a failed cache write only costs a re-decode next time.
        try:
            with _LOCK:  # same lock as delete/drop_photo, so we can't race their cleanup
                if not photo.exists():
                    return  # capture or batch was dropped while we decoded
                # No parents=True: a batch deleted meanwhile must not be resurrected.
                target.parent.mkdir(exist_ok=True)
                tmp = target.with_suffix(".tmp")
                tmp.write_bytes(data)
                os.replace(tmp, target)
                self._unlink_previews(target.parent, capture_id, keep=target)
        except OSError as exc:
            log.debug("preview not cached for capture %s: %s", capture_id, exc)

    @staticmethod
    def _unlink_previews(folder: Path, capture_id: str, keep: Path | None = None) -> None:
        # Every rotation's file for this capture; a turned photo's old previews are dead.
        for stale in folder.glob(f"{capture_id}-r*.jpg"):
            if stale != keep:
                stale.unlink(missing_ok=True)

    def drop_photo(self, batch_id: str, capture: Capture) -> None:
        """Ensure the capture's original photo and all its previews are gone (idempotent)."""
        if not capture.image_file:
            return
        with _LOCK:
            self.photo_path(batch_id, capture).unlink(missing_ok=True)
            self._unlink_previews(self._paths.previews_dir(batch_id), capture.id)

    def delete(self, batch_id: str) -> None:
        # Whole folder: photos must never outlive their batch.
        if not _is_valid_id(batch_id):
            return  # nothing legitimate to delete; never rmtree an unvalidated path
        with _LOCK:
            shutil.rmtree(self._paths.batch_dir(batch_id), ignore_errors=True)

    def delete_if(self, batch_id: str, should_delete: Callable[[Batch], bool]) -> bool:
        # Check and delete under one lock hold so a concurrent user edit cannot land
        # between the janitor's decision and the rmtree.
        with _LOCK:
            try:
                batch = self.get(batch_id)
            except BatchNotFound:
                return False
            if not should_delete(batch):
                return False
            self.delete(batch_id)
            return True

    def _write(self, batch: Batch) -> None:
        write_json_atomic(self._paths.batch_file(batch.id), batch.model_dump(mode="json"))
