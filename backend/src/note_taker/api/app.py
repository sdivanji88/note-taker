import logging
import threading
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, tzinfo
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from note_taker.api import (
    routes_batches,
    routes_books,
    routes_captures,
    routes_settings,
    routes_system,
)
from note_taker.api.auth import SessionTokenMiddleware
from note_taker.api.deps import Services
from note_taker.api.errors import install_error_handlers
from note_taker.batch_store import BatchStore, utcnow
from note_taker.books import BookCatalog
from note_taker.events import EventBus
from note_taker.extraction_queue import ExtractionQueue
from note_taker.extractors.base import Extractor
from note_taker.extractors.factory import build_extractor
from note_taker.git_publisher import GitPublisher
from note_taker.janitor import Janitor
from note_taker.models import ExtractorKind
from note_taker.paths import DataPaths, repo_dir
from note_taker.push_service import PushService
from note_taker.settings_store import SettingsStore

log = logging.getLogger(__name__)

_SIX_HOURS_S = 6 * 3600

def _local_tz() -> tzinfo:
    return datetime.now().astimezone().tzinfo


@dataclass
class AppConfig:
    data_dir: Path
    token: str
    tz: tzinfo = field(default_factory=_local_tz)
    # The Electron renderer: the Vite dev server, or a file:// page (Origin "null").
    allowed_origins: list[str] = field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173", "null"]
    )
    janitor_interval_s: float = _SIX_HOURS_S
    sse_heartbeat_s: float = 15
    health_interval_s: float = 30
    max_upload_bytes: int = 25 * 1024 * 1024
    max_upload_files: int = 100


def _build_services(
    config: AppConfig,
    extractor_provider: Callable[[ExtractorKind | None], Extractor] | None,
    git_factory: Callable[[], GitPublisher] | None,
) -> Services:
    paths = DataPaths(config.data_dir)
    settings_store = SettingsStore(paths)
    settings = settings_store.load
    store = BatchStore(paths)
    events = EventBus()
    books = BookCatalog(
        paths,
        lambda: repo_dir(paths, settings()),
        lambda: settings().notes_repo.books_dir,
    )

    def default_git() -> GitPublisher:
        s = settings()
        return GitPublisher(repo_dir(paths, s), s.notes_repo.remote_url, s.notes_repo.branch)

    def default_provider(kind: ExtractorKind | None) -> Extractor:
        # Built per job from the settings as they are now, so switching model or
        # extractor in Settings applies to the next capture without a restart.
        return build_extractor(settings().extractor, kind)

    git = git_factory or default_git
    provider = extractor_provider or default_provider
    initial = settings()
    return Services(
        paths=paths,
        settings_store=settings_store,
        store=store,
        books=books,
        events=events,
        git_factory=git,
        extractor_provider=provider,
        push=PushService(store, books, git, settings, events, config.tz),
        # Concurrency and timeout are fixed for the queue's lifetime (restart to change).
        queue=ExtractionQueue(
            store,
            provider,
            events,
            concurrency=initial.extractor.concurrency,
            timeout_s=initial.extractor.timeout_s,
            health_interval_s=config.health_interval_s,
        ),
        janitor=Janitor(store, settings, utcnow),
    )


def _startup_step(name: str, step: Callable[[], object]) -> None:
    # A failing step (e.g. a corrupt batch.json during recovery) must not stop the
    # backend from coming up; the user can still fix things through the UI.
    try:
        step()
    except Exception:
        log.exception("startup step failed: %s", name)


def _start_janitor_timer(janitor: Janitor, interval_s: float) -> threading.Event:
    stop = threading.Event()

    def loop() -> None:
        while not stop.wait(interval_s):
            janitor.run()  # never raises

    threading.Thread(target=loop, name="janitor", daemon=True).start()
    return stop


def create_app(
    config: AppConfig,
    extractor_provider: Callable[[ExtractorKind | None], Extractor] | None = None,
    git_factory: Callable[[], GitPublisher] | None = None,
) -> FastAPI:
    services = _build_services(config, extractor_provider, git_factory)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # Recovery first so batches stuck in `pushing` are reconciled before the
        # janitor judges them, and both before the queue starts touching batches.
        _startup_step("push recovery", services.push.recover)
        _startup_step("janitor", services.janitor.run)
        _startup_step("extraction queue", services.queue.start)
        stop_janitor = _start_janitor_timer(services.janitor, config.janitor_interval_s)
        log.info("backend started data_dir=%s", config.data_dir)
        try:
            yield
        finally:
            stop_janitor.set()
            services.queue.stop()
            log.info("backend stopped")

    app = FastAPI(title="note-taker", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.services = services
    app.state.config = config
    install_error_handlers(app)
    for module in (routes_settings, routes_system, routes_books, routes_batches, routes_captures):
        app.include_router(module.router)

    # The last middleware added is the outermost, so CORS wraps the token check:
    # preflights (which carry no token) are answered before it, and 401s still carry
    # CORS headers the renderer can read.
    app.add_middleware(SessionTokenMiddleware, token=config.token)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.allowed_origins,
        allow_methods=["*"],
        allow_headers=["X-Session-Token", "Content-Type"],
    )
    return app
