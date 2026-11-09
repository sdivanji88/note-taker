import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from note_taker.api.deps import ApiError
from note_taker.batch_store import BatchNotFound, UnsupportedImage
from note_taker.books import BookNotFound
from note_taker.git_publisher import GitError
from note_taker.push_service import PushError
from note_taker.redact import mask_credentials

# Every failure leaves the API as {"error": {"code", "message"}}: the renderer has one
# shape to handle, and messages never carry stack traces, file paths or credentials.

log = logging.getLogger(__name__)

_PUSH_ERROR_STATUS = {
    "dirty_repo": 409,
    "not_cloned": 409,
    "nothing_to_push": 400,
    "git_failed": 502,
    "unknown_book": 422,
}

_HTTP_CODES = {404: "not_found", 405: "method_not_allowed", 413: "payload_too_large"}


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError):
        return _error(exc.status, exc.code, mask_credentials(exc.message))

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        # loc + msg only: pydantic's "input" echo could carry whatever the client sent.
        parts = [
            f"{'.'.join(str(p) for p in e.get('loc', ()))}: {e.get('msg', 'invalid')}"
            for e in exc.errors()
        ]
        return _error(422, "invalid_request", "; ".join(parts) or "invalid request")

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException):
        code = _HTTP_CODES.get(exc.status_code, "http_error")
        return _error(exc.status_code, code, str(exc.detail))

    @app.exception_handler(BatchNotFound)
    async def batch_not_found(_: Request, __: BatchNotFound):
        return _error(404, "batch_not_found", "batch not found")

    @app.exception_handler(BookNotFound)
    async def book_not_found(_: Request, __: BookNotFound):
        return _error(404, "book_not_found", "book not found")

    @app.exception_handler(UnsupportedImage)
    async def unsupported_image(_: Request, __: UnsupportedImage):
        return _error(400, "unsupported_type", "only PNG and JPEG images are supported")

    @app.exception_handler(PushError)
    async def push_error(_: Request, exc: PushError):
        status = _PUSH_ERROR_STATUS.get(exc.code, 500)
        if exc.code == "not_cloned":
            # The service's message names the clone path; the UI only needs the remedy.
            message = "the notes repo is not connected; connect it in Settings"
        else:
            message = mask_credentials(str(exc))
        return _error(status, exc.code, message)

    @app.exception_handler(GitError)
    async def git_error(_: Request, exc: GitError):
        log.warning("git failed: %s", mask_credentials(exc.stderr.strip()))
        return _error(502, "git_failed", mask_credentials(exc.stderr.strip()) or "git failed")

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        # Details go to the log only; messages must not leak paths or stack traces.
        log.error("unhandled error", exc_info=exc)
        return _error(500, "internal_error", "internal error; see the backend log")
