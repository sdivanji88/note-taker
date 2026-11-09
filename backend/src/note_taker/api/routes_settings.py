import logging
import re
from pathlib import PurePosixPath, PureWindowsPath
from urllib.parse import urlparse

from fastapi import APIRouter

from note_taker.api.deps import ApiError, Svc
from note_taker.models import Settings
from note_taker.redact import has_credentials, mask_credentials

log = logging.getLogger(__name__)

router = APIRouter()

# git check-ref-format's forbidden characters, plus anything a shell or git could read
# as an option. The branch is passed to git as an argument and into a refspec.
_BAD_BRANCH = re.compile(r"[\s\x00-\x1f\x7f~^:?*\[\\]|\.\.")


def _validate(s: Settings) -> list[str]:
    problems = []
    repo = s.notes_repo

    # books_dir is joined into paths the app writes, commits and rolls back, so it
    # must stay inside the clone.
    books_dir = repo.books_dir
    if (
        not books_dir.strip()
        or books_dir.startswith("-")
        or PurePosixPath(books_dir).is_absolute()
        or PureWindowsPath(books_dir).is_absolute()
        or ".." in PurePosixPath(books_dir.replace("\\", "/")).parts
    ):
        problems.append("notes_repo.books_dir must be a relative path inside the repo")

    if not repo.branch or repo.branch.startswith("-") or _BAD_BRANCH.search(repo.branch):
        problems.append("notes_repo.branch is not a valid branch name")

    url = repo.remote_url
    # ext:: runs arbitrary commands; a leading '-' would be parsed by git as an option.
    if url.startswith("-") or url.lower().startswith("ext::"):
        problems.append("notes_repo.remote_url is not an allowed git remote")

    ex = s.extractor
    if not 1 <= ex.timeout_s <= 3600:
        problems.append("extractor.timeout_s must be between 1 and 3600")
    if not 1 <= ex.concurrency <= 4:
        problems.append("extractor.concurrency must be between 1 and 4")
    if urlparse(ex.ollama.base_url).scheme not in ("http", "https"):
        problems.append("extractor.ollama.base_url must be an http(s) URL")

    if s.batches.expiry_days < 1:
        problems.append("batches.expiry_days must be at least 1")
    if s.batches.warn_days_before < 0:
        problems.append("batches.warn_days_before must not be negative")
    return problems


def _public(s: Settings) -> dict:
    body = s.model_dump(mode="json")
    url = s.notes_repo.remote_url
    body["notes_repo"]["remote_url"] = mask_credentials(url)
    body["remote_url_has_credentials"] = has_credentials(url)
    return body


@router.get("/settings")
def get_settings(svc: Svc) -> dict:
    return _public(svc.settings())


@router.put("/settings")
def put_settings(body: Settings, svc: Svc) -> dict:
    current = svc.settings()
    stored_url = current.notes_repo.remote_url
    # The UI only ever saw the masked URL; echoing it back means "unchanged".
    if has_credentials(stored_url) and body.notes_repo.remote_url == mask_credentials(stored_url):
        body.notes_repo.remote_url = stored_url
    problems = _validate(body)
    if problems:
        raise ApiError(422, "invalid_settings", "; ".join(problems))
    svc.settings_store.save(body)
    log.info(
        "settings updated extractor=%s branch=%s books_dir=%s",
        body.extractor.kind.value, body.notes_repo.branch, body.notes_repo.books_dir,
    )
    return _public(body)
