import io
import logging

from api_helpers import H
from fastapi.testclient import TestClient

from note_taker.redact import RedactingFilter

URL = "https://me:ghp_SECRET@github.com/me/notes.git"


def _record(exc: BaseException | None = None, stack_info: str | None = None) -> logging.LogRecord:
    exc_info = (type(exc), exc, exc.__traceback__) if exc else None
    return logging.LogRecord(
        "x", logging.ERROR, __file__, 1, "failed", None, exc_info, sinfo=stack_info
    )


def _formatted(record: logging.LogRecord) -> str:
    RedactingFilter().filter(record)
    return logging.Formatter("%(message)s").format(record)


def _raised(make: callable) -> BaseException:
    try:
        make()
    except Exception as exc:  # noqa: BLE001 - we only want the traceback-bearing instance
        return exc
    raise AssertionError("did not raise")


def _boom():
    raise RuntimeError(f"clone failed: {URL}")


def test_exc_info_credentials_are_masked():
    out = _formatted(_record(_raised(_boom)))
    assert "ghp_SECRET" not in out
    assert "https://***@github.com/me/notes.git" in out
    assert "Traceback" in out  # redacted, not dropped: the trace is still useful


def test_chained_cause_credentials_are_masked():
    def outer():
        try:
            _boom()
        except RuntimeError as cause:
            raise ValueError("wrapper") from cause

    out = _formatted(_record(_raised(outer)))
    assert "ghp_SECRET" not in out
    assert "wrapper" in out


def test_stack_info_credentials_are_masked():
    out = _formatted(_record(stack_info=f"Stack (most recent call last):\n  remote={URL}"))
    assert "ghp_SECRET" not in out
    assert "remote=https://***@github.com" in out


def test_token_query_param_in_exception_is_masked():
    exc = _raised(lambda: (_ for _ in ()).throw(RuntimeError("GET /x?token=abc123 failed")))
    assert "abc123" not in _formatted(_record(exc))


def test_unhandled_error_log_has_no_credentials(client, monkeypatch):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        svc = client.app.state.services

        def boom():
            raise RuntimeError(f"clone failed: {URL}")

        monkeypatch.setattr(svc.store, "list", boom)
        r = TestClient(client.app, raise_server_exceptions=False).get("/batches", headers=H)
    finally:
        root.removeHandler(handler)
    assert r.status_code == 500
    logged = stream.getvalue()
    assert "unhandled error" in logged and "RuntimeError" in logged
    assert "ghp_SECRET" not in logged
