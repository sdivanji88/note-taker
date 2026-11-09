import logging
import time
from datetime import timedelta

import pytest
from api_helpers import (
    TOKEN,
    H,
    error_code,
    kindle,
    new_batch,
    upload,
    wait_status,
    wait_until,
)
from fastapi.testclient import TestClient

from note_taker.api.app import AppConfig, create_app
from note_taker.extractors.fake import FakeExtractor
from note_taker.models import BatchStatus, ExtractorKind

# Tesseract isn't installed here; rotation guessing must be inert and fast.
pytestmark = pytest.mark.usefixtures("no_osd")


@pytest.mark.parametrize("path", ["/health", "/settings", "/books", "/batches", "/no-such-route"])
def test_requires_token(client, path):
    for headers in ({}, {"X-Session-Token": "wrong"}, {"X-Session-Token": ""}):
        r = client.get(path, headers=headers)
        assert r.status_code == 401, (path, headers)
        assert error_code(r) == "unauthorized"
    assert client.get(path, headers=H).status_code in (200, 404)


def test_requires_token_for_writes(client):
    r = client.post("/batches", json={})
    assert r.status_code == 401
    assert client.get("/batches", headers=H).json() == []


def test_token_query_param_allowed_only_for_image_and_events(client, make_image):
    b = new_batch(client)
    cid = upload(client, b, make_image("page.png")).json()["created"][0]["id"]

    for path in ("/health", f"/batches/{b}", "/batches", f"/captures/{cid}/retry"):
        assert client.get(f"{path}?token={TOKEN}").status_code == 401, path
    assert client.post(f"/batches?token={TOKEN}", json={}).status_code == 401

    assert client.get(f"/captures/{cid}/image?token={TOKEN}").status_code == 200
    assert client.get(f"/captures/{cid}/image?token=wrong").status_code == 401
    assert client.get(f"/captures/{cid}/image").status_code == 401
    with client.stream("GET", f"/batches/{b}/events?token={TOKEN}") as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
    assert client.get(f"/batches/{b}/events?token=wrong").status_code == 401


def test_cors_preflight_answered_without_token(client):
    r = client.options(
        "/batches",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-session-token, content-type",
        },
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "x-session-token" in r.headers["access-control-allow-headers"].lower()


def test_cors_rejects_unknown_origin_preflight(client):
    r = client.options(
        "/batches",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert r.status_code == 400
    assert "access-control-allow-origin" not in r.headers


def test_cors_allowed_origin_still_needs_token(client):
    origin = {"Origin": "http://localhost:5173"}
    r = client.get("/batches", headers=origin)
    assert r.status_code == 401
    # The renderer can read the 401 and show it.
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert client.get("/batches", headers={**origin, **H}).status_code == 200


def test_unknown_route_and_method_use_error_shape(client):
    r = client.get("/nope", headers=H)
    assert r.status_code == 404
    assert error_code(r) == "not_found"
    r = client.put("/batches", headers=H, json={})
    assert r.status_code == 405
    assert error_code(r) == "method_not_allowed"


def test_validation_errors_use_error_shape_without_echoing_input(client):
    b = new_batch(client)
    c = kindle(client, b)
    r = client.patch(f"/captures/{c['id']}", headers=H, json={"page": "sekrit-value"})
    assert r.status_code == 422
    assert error_code(r) == "invalid_request"
    assert "sekrit-value" not in r.text
    r = client.post("/books", headers=H, content=b"{not json", )
    assert r.status_code == 422
    assert error_code(r) == "invalid_request"


def test_unhandled_error_is_500_without_details(client, monkeypatch):
    svc = client.app.state.services

    def boom():
        raise RuntimeError("/Users/someone/secret/path exploded")

    monkeypatch.setattr(svc.store, "list", boom)
    raw = TestClient(client.app, raise_server_exceptions=False)
    r = raw.get("/batches", headers=H)
    assert r.status_code == 500
    assert error_code(r) == "internal_error"
    assert "secret" not in r.text and "Traceback" not in r.text


def test_mask_credentials():
    from note_taker.redact import has_credentials, mask_credentials

    assert mask_credentials("fatal: unable to access 'https://me:tok@github.com/x.git/'") == (
        "fatal: unable to access 'https://***@github.com/x.git/'"
    )
    assert mask_credentials("GET /batches/1/events?token=abc&x=1 HTTP/1.1") == (
        "GET /batches/1/events?token=***&x=1 HTTP/1.1"
    )
    assert mask_credentials("git@github.com:me/notes.git") == "git@github.com:me/notes.git"
    assert has_credentials("https://tok@github.com/x") is True
    assert has_credentials("https://github.com/x") is False


def test_redacting_filter_masks_formatted_log_records():
    from note_taker.redact import RedactingFilter

    record = logging.LogRecord("x", logging.ERROR, __file__, 1, "push failed: %s", ("https://u:p@h/r",), None)
    assert RedactingFilter().filter(record) is True
    assert record.getMessage() == "push failed: https://***@h/r"


def test_startup_runs_recover_then_janitor_then_queue_and_shutdown_stops(tmp_path, monkeypatch):
    from note_taker.extraction_queue import ExtractionQueue
    from note_taker.janitor import Janitor, JanitorReport
    from note_taker.push_service import PushService

    calls = []
    monkeypatch.setattr(PushService, "recover", lambda self: calls.append("recover"))
    monkeypatch.setattr(Janitor, "run", lambda self: calls.append("janitor") or JanitorReport())
    monkeypatch.setattr(ExtractionQueue, "start", lambda self: calls.append("queue.start"))
    monkeypatch.setattr(ExtractionQueue, "stop", lambda self: calls.append("queue.stop"))
    app = create_app(AppConfig(data_dir=tmp_path / "d", token=TOKEN), extractor_provider=lambda k: FakeExtractor())
    with TestClient(app):
        assert calls == ["recover", "janitor", "queue.start"]
    assert calls[-1] == "queue.stop"


def test_startup_reopens_batch_stuck_in_pushing(tmp_path):
    from note_taker.batch_store import BatchStore
    from note_taker.paths import DataPaths

    store = BatchStore(DataPaths(tmp_path / "d"))
    batch = store.create(None)
    batch.status = BatchStatus.pushing
    store.save(batch)
    app = create_app(AppConfig(data_dir=tmp_path / "d", token=TOKEN), extractor_provider=lambda k: FakeExtractor())
    with TestClient(app) as client:
        assert client.get(f"/batches/{batch.id}", headers=H).json()["status"] == "open"


def test_startup_janitor_deletes_expired_warned_batch(tmp_path):
    from note_taker.batch_store import BatchStore
    from note_taker.paths import DataPaths

    store = BatchStore(DataPaths(tmp_path / "d"))
    batch = store.create(None)
    store.add_kindle(batch.id, [], None, None, None, None)

    def expire(b):
        b.updated_at = b.updated_at - timedelta(days=40)
        b.warned_at = b.updated_at + timedelta(days=24)

    store.modify(batch.id, expire, touch=False)
    app = create_app(AppConfig(data_dir=tmp_path / "d", token=TOKEN), extractor_provider=lambda k: FakeExtractor())
    with TestClient(app) as client:
        assert client.get(f"/batches/{batch.id}", headers=H).status_code == 404


def test_startup_resumes_pending_photo_captures(tmp_path, make_image, fake):
    from note_taker.batch_store import BatchStore
    from note_taker.paths import DataPaths

    store = BatchStore(DataPaths(tmp_path / "d"))
    batch = store.create(None)
    cap = store.add_photo(batch.id, "page.png", make_image("page.png").read_bytes())
    app = create_app(AppConfig(data_dir=tmp_path / "d", token=TOKEN), extractor_provider=lambda k: fake)
    with TestClient(app) as client:
        wait_status(client, batch.id, cap.id, "ready")


def test_janitor_reruns_on_a_timer(tmp_path, monkeypatch):
    from note_taker.janitor import Janitor, JanitorReport

    runs = []
    monkeypatch.setattr(Janitor, "run", lambda self: runs.append(1) or JanitorReport())
    config = AppConfig(data_dir=tmp_path / "d", token=TOKEN, janitor_interval_s=0.05)
    with TestClient(create_app(config, extractor_provider=lambda k: FakeExtractor())):
        wait_until(lambda: len(runs) >= 3)
    stopped_at = len(runs)
    time.sleep(0.2)
    assert len(runs) <= stopped_at + 1  # the timer stops with the app


def test_failing_startup_step_does_not_stop_the_app(tmp_path, monkeypatch):
    from note_taker.push_service import PushService

    def broken(self):
        raise RuntimeError("corrupt batch.json")

    monkeypatch.setattr(PushService, "recover", broken)
    app = create_app(AppConfig(data_dir=tmp_path / "d", token=TOKEN), extractor_provider=lambda k: FakeExtractor())
    with TestClient(app) as client:
        assert client.get("/batches", headers=H).status_code == 200


def test_default_extractor_provider_uses_current_settings(tmp_path):
    from note_taker.extractors.ollama import OllamaVisionExtractor
    from note_taker.extractors.tesseract import TesseractExtractor

    app = create_app(AppConfig(data_dir=tmp_path / "d", token=TOKEN))
    provider = app.state.services.extractor_provider
    assert isinstance(provider(None), OllamaVisionExtractor)
    client = TestClient(app)  # no lifespan: nothing to extract
    s = client.get("/settings", headers=H).json()
    s["extractor"]["kind"] = "tesseract"
    assert client.put("/settings", headers=H, json=s).status_code == 200
    assert isinstance(provider(None), TesseractExtractor)
    assert isinstance(provider(ExtractorKind.ollama), OllamaVisionExtractor)


def test_cli_binds_localhost_with_args(tmp_path, monkeypatch):
    import uvicorn
    from fastapi import FastAPI

    from note_taker import __main__ as cli
    from note_taker.redact import RedactingFilter

    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(app=app, **kw))
    cli.main(["--port", "8765", "--token", "t", "--data-dir", str(tmp_path / "d")])
    assert isinstance(seen["app"], FastAPI)
    assert seen["host"] == "127.0.0.1"
    assert seen["port"] == 8765
    assert seen["app"].state.config.data_dir == tmp_path / "d"
    assert any(isinstance(f, RedactingFilter) for h in logging.getLogger().handlers for f in h.filters)


def test_cli_requires_all_args(capsys):
    from note_taker import __main__ as cli

    with pytest.raises(SystemExit):
        cli.main(["--port", "8765"])
