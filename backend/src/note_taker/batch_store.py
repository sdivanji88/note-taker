# Deferred annotations: the `list()` method would otherwise shadow the builtin in later signatures.
from __future__ import annotations

import hashlib
import shutil
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from ulid import ULID

from note_taker.jsonio import read_json, write_json_atomic
from note_taker.models import Batch, Capture, CaptureStatus, Highlight, Source
from note_taker.paths import DataPaths


class BatchNotFound(Exception):
    pass


class UnsupportedImage(Exception):
    pass


class DuplicatePhoto(Exception):
    pass


def utcnow() -> datetime:
    return datetime.now(UTC)


def captured_at(data: bytes, fallback: datetime) -> datetime:
    # Stub: Task 7 replaces this with imaging.captured_at (EXIF timestamp).
    return fallback


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
        with _LOCK:
            root = self._paths.batches_dir
            if not root.exists():
                return []
            batches = [
                Batch.model_validate(data)
                for d in root.iterdir()
                if (data := read_json(d / "batch.json")) is not None
            ]
        return sorted(batches, key=lambda b: b.created_at)

    def save(self, batch: Batch, touch: bool = True) -> Batch:
        # Background work (extraction) passes touch=False so it doesn't reset expiry.
        with _LOCK:
            if touch:
                batch.updated_at = self._now()
            self._write(batch)
            return batch

    def add_photo(self, batch_id: str, filename: str, data: bytes) -> Capture:
        ext = _sniff_extension(data)
        if ext is None:
            raise UnsupportedImage(filename)
        sha = hashlib.sha256(data).hexdigest()
        with _LOCK:
            batch = self.get(batch_id)
            if any(c.image_sha256 == sha for c in batch.captures):
                raise DuplicatePhoto(filename)
            capture = Capture(
                source=Source.photo,
                image_sha256=sha,
                captured_at=captured_at(data, self._now()),
            )
            capture.image_file = f"{capture.id}.{ext}"
            photo = self._paths.photos_dir(batch_id) / capture.image_file
            photo.parent.mkdir(parents=True, exist_ok=True)
            photo.write_bytes(data)
            batch.captures.append(capture)
            try:
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
                if c.id == capture_id and c.image_file:
                    self.photo_path(batch_id, c).unlink(missing_ok=True)
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

    def delete(self, batch_id: str) -> None:
        # Whole folder: photos must never outlive their batch.
        if not _is_valid_id(batch_id):
            return  # nothing legitimate to delete; never rmtree an unvalidated path
        with _LOCK:
            shutil.rmtree(self._paths.batch_dir(batch_id), ignore_errors=True)

    def _write(self, batch: Batch) -> None:
        write_json_atomic(self._paths.batch_file(batch.id), batch.model_dump(mode="json"))
