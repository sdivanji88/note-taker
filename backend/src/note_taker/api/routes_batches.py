import asyncio
import json
import logging
from dataclasses import asdict

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict
from sse_starlette import EventSourceResponse

from note_taker.api.deps import ApiError, Services, Svc, ensure_not_pushing
from note_taker.janitor import expiring_soon
from note_taker.models import Batch, BatchStatus, CaptureStatus

log = logging.getLogger(__name__)

router = APIRouter()

# How often the SSE generator checks its thread-fed queue; small enough to feel live.
_EVENT_POLL_S = 0.05


class BatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    default_book_slug: str | None = None


class BatchPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    default_book_slug: str | None


def _expiry(batch: Batch, svc: Services) -> dict:
    settings = svc.settings()
    return {
        "expires_at": batch.expires_at(settings.batches.expiry_days).isoformat(),
        "expiring_soon": expiring_soon(batch, settings, svc.now()),
    }


def batch_view(batch: Batch, svc: Services) -> dict:
    return {**batch.model_dump(mode="json"), **_expiry(batch, svc)}


def _summary(batch: Batch, svc: Services) -> dict:
    counts = {s.value: 0 for s in CaptureStatus}
    for c in batch.captures:
        counts[c.status.value] += 1
    return {
        "id": batch.id,
        "status": batch.status.value,
        "default_book_slug": batch.default_book_slug,
        "created_at": batch.created_at.isoformat(),
        "updated_at": batch.updated_at.isoformat(),
        "warned_at": batch.warned_at.isoformat() if batch.warned_at else None,
        **_expiry(batch, svc),
        "counts": counts,
    }


@router.get("/batches")
def list_batches(svc: Svc) -> list[dict]:
    return [_summary(b, svc) for b in svc.store.list()]


@router.post("/batches")
def create_batch(body: BatchIn, svc: Svc) -> dict:
    if body.default_book_slug is not None:
        svc.require_book(body.default_book_slug)
    batch = svc.store.create(body.default_book_slug)
    log.info("batch created id=%s", batch.id)
    return batch_view(batch, svc)


@router.get("/batches/{batch_id}")
def get_batch(batch_id: str, svc: Svc) -> dict:
    return batch_view(svc.store.get(batch_id), svc)


@router.patch("/batches/{batch_id}")
def patch_batch(batch_id: str, body: BatchPatch, svc: Svc) -> dict:
    svc.store.get(batch_id)  # 404 before 422: an unknown batch is the bigger problem
    if body.default_book_slug is not None:
        svc.require_book(body.default_book_slug)

    def change(b: Batch) -> None:
        ensure_not_pushing(b)
        b.default_book_slug = body.default_book_slug

    return batch_view(svc.store.modify(batch_id, change), svc)


@router.delete("/batches/{batch_id}", status_code=204)
def delete_batch(batch_id: str, svc: Svc) -> Response:
    # BatchStore.delete is a silent no-op for unknown ids; the client deserves a 404.
    batch = svc.store.get(batch_id)
    ensure_not_pushing(batch)
    if not svc.store.delete_if(batch_id, lambda b: b.status is not BatchStatus.pushing):
        # A push started (409) or the batch vanished (404) since the read above.
        ensure_not_pushing(svc.store.get(batch_id))
        raise ApiError(409, "batch_pushing", "this batch is being pushed; try again shortly")
    log.info("batch deleted id=%s", batch_id)
    return Response(status_code=204)


@router.post("/batches/{batch_id}/push")
def push_batch(batch_id: str, svc: Svc) -> dict:
    svc.store.get(batch_id)  # 404 for an unknown batch rather than a git error
    return asdict(svc.push.push(batch_id))


@router.get("/batches/{batch_id}/events")
def batch_events(batch_id: str, request: Request, svc: Svc) -> EventSourceResponse:
    svc.store.get(batch_id)

    async def stream():
        # Subscribed here, not in the route: a generator that never starts never runs
        # its finally, so a queue created outside it could leak.
        q = svc.events.subscribe(batch_id)
        try:
            while True:
                while not q.empty():
                    event = q.get_nowait()
                    yield {"event": event["type"], "data": json.dumps(event["data"])}
                await asyncio.sleep(_EVENT_POLL_S)
        finally:
            # Also runs when the client disconnects (the generator is cancelled), so a
            # closed tab never leaves a queue filling up forever.
            svc.events.unsubscribe(batch_id, q)

    # ping = heartbeat comment, so proxies and the renderer can tell a quiet stream
    # from a dead one.
    return EventSourceResponse(stream(), ping=request.app.state.config.sse_heartbeat_s)
