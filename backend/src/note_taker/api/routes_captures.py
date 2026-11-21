import io
import logging
from datetime import datetime

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from starlette.concurrency import run_in_threadpool

from note_taker import imaging
from note_taker.api.deps import ApiError, Services, Svc, ensure_not_pushing
from note_taker.api.uploads import UploadedFile, stream_files
from note_taker.batch_store import BatchNotFound, DuplicatePhoto, UnsupportedImage
from note_taker.books import BookNotFound
from note_taker.models import (
    Batch,
    Capture,
    CaptureStatus,
    ExtractorKind,
    Highlight,
    Source,
)

log = logging.getLogger(__name__)

router = APIRouter()

S = CaptureStatus

# Status changes a client may request (spec §6). Everything else (pending, extracting,
# pushed) is the extraction queue's or the push's to set; retry has its own route.
_TRANSITIONS: dict[CaptureStatus, set[CaptureStatus]] = {
    S.ready: {S.approved, S.discarded},
    S.approved: {S.ready},
    S.failed: {S.ready, S.discarded},
    # The extraction result would overwrite anything typed now, so the only thing a
    # user may do with an unfinished capture is throw it away.
    S.pending: {S.discarded},
    S.extracting: {S.discarded},
}
_FIELDS = ("highlights", "book_slug", "page", "chapter", "captured_at", "rotation")
_UNFINISHED = {S.pending, S.extracting}
# Rotation is a correction to a finished extraction; it doesn't re-run it (retry does).
_ROTATABLE = {S.ready, S.failed}
_RETRYABLE = {S.failed, S.pending}


class HighlightIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str | None = None
    text: str
    note: str | None = None


class KindleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Source
    highlights: list[HighlightIn]
    book_slug: str | None = None
    page: int | None = Field(default=None, ge=0)
    chapter: str | None = None
    captured_at: datetime | None = None

    @field_validator("source")
    @classmethod
    def _kindle_only(cls, v: Source) -> Source:
        if v is not Source.kindle:
            raise ValueError("JSON bodies create kindle captures; upload photos as multipart")
        return v


class CapturePatch(BaseModel):
    # Whitelist: image_file, image_sha256, id, source, error and extractor_used are
    # the backend's, so a body naming them is rejected rather than silently trusted.
    model_config = ConfigDict(extra="forbid")
    highlights: list[HighlightIn] | None = None
    book_slug: str | None = None
    page: int | None = Field(default=None, ge=0)
    chapter: str | None = None
    captured_at: datetime | None = None
    rotation: int | None = None
    status: CaptureStatus | None = None

    @field_validator("rotation")
    @classmethod
    def _quarter_turn(cls, v: int | None) -> int | None:
        if v is not None and v not in (0, 90, 180, 270):
            raise ValueError("rotation must be one of 0, 90, 180, 270")
        return v


class RetryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    extractor: ExtractorKind | None = None


def _find(svc: Services, capture_id: str) -> tuple[Batch, Capture]:
    try:
        return svc.store.find_capture(capture_id)
    except BatchNotFound:
        raise ApiError(404, "capture_not_found", "capture not found") from None


def _in(batch: Batch, capture_id: str) -> Capture:
    for c in batch.captures:
        if c.id == capture_id:
            return c
    # Removed by a concurrent request between lookup and the locked modify.
    raise ApiError(404, "capture_not_found", "capture not found")


def _highlights(incoming: list[HighlightIn], existing: list[Highlight]) -> list[Highlight]:
    # Highlight ids are written into markdown markers that make pushes idempotent, so a
    # known id is kept across edits, and an id we didn't mint is never accepted.
    known = {h.id for h in existing}
    return [
        Highlight(text=h.text, note=h.note, **({"id": h.id} if h.id in known else {}))
        for h in incoming
    ]


def _approvable(capture: Capture, batch: Batch, svc: Services) -> str | None:
    if not any(h.text.strip() for h in capture.highlights):
        return "add at least one highlight with text before approving"
    slug = capture.book_slug or batch.default_book_slug
    if not slug:
        return "choose a book (for this page or the batch) before approving"
    try:
        svc.books.get(slug)
    except BookNotFound:
        return f"book {slug!r} no longer exists"
    return None


def _view(capture: Capture) -> dict:
    return capture.model_dump(mode="json")


# --- create -----------------------------------------------------------------------


@router.post("/batches/{batch_id}/captures")
async def add_captures(batch_id: str, request: Request, svc: Svc) -> dict:
    # async only to read the body; every store/queue call runs in the threadpool.
    await run_in_threadpool(svc.store.get, batch_id)
    if request.headers.get("content-type", "").startswith("multipart/form-data"):
        return await _add_photos(batch_id, request, svc)
    try:
        body = KindleIn.model_validate_json(await request.body())
    except ValidationError as exc:
        parts = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
        raise ApiError(422, "invalid_request", "; ".join(parts)) from None
    return await run_in_threadpool(_add_kindle, batch_id, body, svc)


def _add_kindle(batch_id: str, body: KindleIn, svc: Services) -> dict:
    if body.book_slug is not None:
        svc.require_book(body.book_slug)
    capture = svc.store.add_kindle(
        batch_id,
        [Highlight(text=h.text, note=h.note) for h in body.highlights],
        body.book_slug,
        body.page,
        body.chapter,
        body.captured_at,
    )
    log.info("kindle capture added batch=%s capture=%s highlights=%d", batch_id, capture.id, len(capture.highlights))
    return _view(capture)


async def _add_photos(batch_id: str, request: Request, svc: Services) -> dict:
    config = request.app.state.config
    declared = request.headers.get("content-length")
    # Refuse an obviously oversized body before reading any of it.
    ceiling = config.max_upload_files * config.max_upload_bytes + 1024 * 1024
    if declared and declared.isdigit() and int(declared) > ceiling:
        raise ApiError(413, "payload_too_large", "upload is larger than the per-request limit")

    created: list[dict] = []
    rejected: list[dict] = []
    seen = 0
    async for upload in stream_files(request, config.max_upload_bytes):
        seen += 1
        if seen > config.max_upload_files:
            rejected.append({"filename": upload.filename, "reason": "too_many_files"})
            continue
        result = await run_in_threadpool(_store_photo, batch_id, upload, svc)
        (created if "id" in result else rejected).append(result)
    log.info("photos uploaded batch=%s created=%d rejected=%d", batch_id, len(created), len(rejected))
    return {"created": created, "rejected": rejected}


def _store_photo(batch_id: str, upload: UploadedFile, svc: Services) -> dict:
    # One bad file is reported in `rejected`, never fails the request.
    if upload.too_large:
        return {"filename": upload.filename, "reason": "too_large"}
    try:
        capture = svc.store.add_photo(batch_id, upload.filename, upload.data)
    except UnsupportedImage:
        return {"filename": upload.filename, "reason": "unsupported_type"}
    except DuplicatePhoto:
        return {"filename": upload.filename, "reason": "duplicate"}
    svc.queue.enqueue(batch_id, capture.id)
    return _view(capture)


# --- read / edit ------------------------------------------------------------------


@router.get("/captures/{capture_id}/image")
def capture_image(capture_id: str, svc: Svc) -> Response:
    batch, capture = _find(svc, capture_id)
    if not capture.image_file:
        raise ApiError(404, "no_image", "this capture has no photo")
    path = svc.store.photo_path(batch.id, capture)
    try:
        img = imaging.load_upright(path, capture.rotation).convert("RGB")
    except FileNotFoundError:
        raise ApiError(404, "no_image", "the photo for this capture is missing") from None
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return Response(buf.getvalue(), media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.patch("/captures/{capture_id}")
def patch_capture(capture_id: str, body: CapturePatch, svc: Svc) -> dict:
    batch, _ = _find(svc, capture_id)
    fields = body.model_fields_set
    if "book_slug" in fields and body.book_slug is not None:
        svc.require_book(body.book_slug)
    previous: CaptureStatus | None = None
    updated: Capture | None = None

    def change(b: Batch) -> None:
        nonlocal previous, updated
        ensure_not_pushing(b)
        c = _in(b, capture_id)
        previous = c.status
        # Judged here, on the copy being written under the store lock, so the
        # extraction worker can't claim or finish the capture between check and write.
        if c.status is S.pushed:
            raise ApiError(409, "invalid_transition", "a pushed capture can no longer be edited")
        edited = [f for f in _FIELDS if f in fields]
        if edited and c.status in _UNFINISHED:
            raise ApiError(
                409, "invalid_transition", f"cannot edit a {c.status.value} capture; wait for extraction to finish"
            )
        if "rotation" in fields and c.status not in _ROTATABLE:
            raise ApiError(409, "invalid_transition", f"cannot rotate a {c.status.value} capture")
        if body.status is not None and body.status is not c.status:
            if body.status not in _TRANSITIONS.get(c.status, set()):
                raise ApiError(
                    409, "invalid_transition", f"cannot change status from {c.status.value} to {body.status.value}"
                )
            if c.status is S.failed:
                c.error = None  # fixed by hand: the extraction error no longer applies
            c.status = body.status
        if "highlights" in fields:
            c.highlights = _highlights(body.highlights or [], c.highlights)
        for name in ("book_slug", "page", "chapter"):
            if name in fields:
                setattr(c, name, getattr(body, name))
        if "captured_at" in fields and body.captured_at is not None:
            c.captured_at = body.captured_at
        if "rotation" in fields and body.rotation is not None:
            c.rotation = body.rotation
        # Checked on the result, so an edit can't empty an already-approved capture either.
        if c.status is S.approved and (problem := _approvable(c, b, svc)):
            raise ApiError(422, "not_approvable", problem)
        updated = c

    # touch=True (the default): any user edit restarts the batch's expiry clock.
    svc.store.modify(batch.id, change)
    if updated.status is not previous:
        _publish_status(svc, batch.id, updated)
    return _view(updated)


@router.post("/captures/{capture_id}/retry")
def retry_capture(capture_id: str, svc: Svc, body: RetryIn | None = None) -> dict:
    batch, _ = _find(svc, capture_id)
    kind = body.extractor if body else None
    updated: Capture | None = None

    def change(b: Batch) -> None:
        nonlocal updated
        ensure_not_pushing(b)
        c = _in(b, capture_id)
        if not c.image_file:
            raise ApiError(409, "invalid_transition", "only photo captures can be re-extracted")
        if c.status not in _RETRYABLE:
            raise ApiError(409, "invalid_transition", f"cannot retry a {c.status.value} capture")
        c.status = S.pending
        c.error = None
        updated = c

    svc.store.modify(batch.id, change)
    svc.queue.enqueue(batch.id, capture_id, kind=kind)
    log.info("capture retry batch=%s capture=%s extractor=%s", batch.id, capture_id, kind or "default")
    _publish_status(svc, batch.id, updated)
    return _view(updated)


@router.delete("/captures/{capture_id}", status_code=204)
def delete_capture(capture_id: str, svc: Svc) -> Response:
    batch, _ = _find(svc, capture_id)
    removed: Capture | None = None

    def change(b: Batch) -> None:
        nonlocal removed
        ensure_not_pushing(b)
        removed = _in(b, capture_id)
        b.captures = [c for c in b.captures if c.id != capture_id]

    svc.store.modify(batch.id, change)
    if removed.image_file:
        # After the batch.json write: a crash in between leaves an orphan photo in the
        # batch folder (deleted with the batch), never a capture pointing at nothing.
        svc.store.photo_path(batch.id, removed).unlink(missing_ok=True)
    log.info("capture deleted batch=%s capture=%s", batch.id, capture_id)
    return Response(status_code=204)


def _publish_status(svc: Services, batch_id: str, capture: Capture) -> None:
    svc.events.publish(
        batch_id,
        "capture.status_changed",
        {"capture_id": capture.id, "status": capture.status.value, "error": capture.error},
    )
