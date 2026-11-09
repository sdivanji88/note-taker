import logging
from dataclasses import asdict

from fastapi import APIRouter

from note_taker.api.deps import ApiError, Services, Svc
from note_taker.git_publisher import GitError
from note_taker.redact import mask_credentials

log = logging.getLogger(__name__)

router = APIRouter()


def _git_detail(exc: GitError) -> str:
    return mask_credentials(exc.stderr.strip()) or "git failed"


def _extractor_health(svc: Services) -> dict:
    kind = svc.settings().extractor.kind.value
    try:
        status = svc.extractor_provider(None).health()
        return {"kind": kind, "ok": status.ok, "detail": mask_credentials(status.detail)}
    except Exception as exc:  # noqa: BLE001 - a broken extractor is a health result, not a 500
        return {"kind": kind, "ok": False, "detail": mask_credentials(str(exc) or type(exc).__name__)}


def _repo_health(svc: Services) -> dict:
    git = svc.git_factory()
    cloned = git.is_cloned()
    dirty = None
    if cloned:
        try:
            dirty = git.is_dirty(svc.settings().notes_repo.books_dir)
        except GitError as exc:
            log.warning("health: dirty check failed: %s", _git_detail(exc))
    return {"cloned": cloned, "dirty": dirty, "path": str(git.repo_dir)}


def _remote_health(svc: Services) -> dict:
    git = svc.git_factory()
    if not git.remote_url:
        return {"ok": False, "detail": "no remote configured"}
    try:
        git.check_remote()
    except GitError as exc:
        return {"ok": False, "detail": _git_detail(exc)}
    return {"ok": True, "detail": "ok"}


@router.get("/health")
def health(svc: Svc) -> dict:
    return {"extractor": _extractor_health(svc), "repo": _repo_health(svc), "remote": _remote_health(svc)}


@router.post("/repo/connect")
def connect_repo(svc: Svc) -> dict:
    git = svc.git_factory()
    if not git.remote_url:
        raise ApiError(400, "no_remote", "set the notes repo remote URL in Settings first")
    if not git.is_cloned():
        try:
            # check_remote first: its error (auth, missing branch) is clearer than clone's.
            git.check_remote()
            git.clone()
        except GitError as exc:
            detail = _git_detail(exc)
            log.warning("repo connect failed: %s", detail)
            raise ApiError(400, "git_failed", detail) from None
        log.info("repo connected remote=%s", mask_credentials(git.remote_url))
    return _repo_health(svc)


@router.post("/janitor/run")
def run_janitor(svc: Svc) -> dict:
    return asdict(svc.janitor.run())
