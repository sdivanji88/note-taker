from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request

from note_taker.batch_store import BatchStore, utcnow
from note_taker.books import BookCatalog, BookNotFound
from note_taker.events import EventBus
from note_taker.extraction_queue import ExtractionQueue
from note_taker.extractors.base import Extractor
from note_taker.git_publisher import GitPublisher
from note_taker.janitor import Janitor
from note_taker.models import Batch, BatchStatus, ExtractorKind, Settings
from note_taker.paths import DataPaths, repo_dir
from note_taker.push_service import PushService
from note_taker.settings_store import SettingsStore


class ApiError(Exception):
    """Raised by routes; rendered as {"error": {"code", "message"}} with `status`."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


@dataclass
class Services:
    """Everything a route needs, built once per app so tests get an isolated world."""

    paths: DataPaths
    settings_store: SettingsStore
    store: BatchStore
    books: BookCatalog
    events: EventBus
    git_factory: Callable[[], GitPublisher]
    extractor_provider: Callable[[ExtractorKind | None], Extractor]
    push: PushService
    queue: ExtractionQueue
    janitor: Janitor
    now: Callable[[], datetime] = utcnow

    def settings(self) -> Settings:
        # Read on every call: PUT /settings must take effect without a restart.
        return self.settings_store.load()

    def repo_dir(self) -> Path:
        return repo_dir(self.paths, self.settings())

    def require_book(self, slug: str) -> None:
        """A book slug from a request body must name a repo or pending book (422 otherwise)."""
        try:
            self.books.get(slug)
        except BookNotFound:
            raise ApiError(422, "unknown_book", f"no such book: {slug!r}") from None


def get_services(request: Request) -> Services:
    return request.app.state.services


Svc = Annotated[Services, Depends(get_services)]


def ensure_not_pushing(batch: Batch) -> None:
    # A push snapshots the batch, writes markdown, then marks captures pushed; edits
    # while it runs would race that bookkeeping, so they wait until it finishes.
    if batch.status is BatchStatus.pushing:
        raise ApiError(409, "batch_pushing", "this batch is being pushed; try again shortly")
