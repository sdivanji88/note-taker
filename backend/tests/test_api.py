import json
import logging
import subprocess
import threading
import time
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from note_taker import imaging
from note_taker.api.app import AppConfig, create_app
from note_taker.extractors.fake import FakeExtractor
from note_taker.models import (
    BatchStatus,
    ExtractedHighlight,
    ExtractionResult,
    ExtractorKind,
)

TOKEN = "s3cret-token"
H = {"X-Session-Token": TOKEN}


@pytest.fixture(autouse=True)
def no_osd(monkeypatch):
    # Tesseract isn't installed here; rotation guessing must be inert and fast.
    monkeypatch.setattr(imaging, "detect_rotation", lambda path: 0)


def wait_until(cond, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.02)
    raise AssertionError("condition not met in time")


def remote_text(remote: Path, rel: str) -> str | None:
    r = subprocess.run(
        ["git", "-C", str(remote), "show", f"main:{rel}"], check=False, capture_output=True, text=True
    )
    return r.stdout if r.returncode == 0 else None


def error_code(resp) -> str:
    body = resp.json()
    assert set(body) == {"error"}, body
    assert set(body["error"]) == {"code", "message"}, body
    return body["error"]["code"]


@pytest.fixture
def fake():
    return FakeExtractor(
        result=ExtractionResult(highlights=[ExtractedHighlight(text="mathematical possibility")])
    )


@pytest.fixture
def make_app(tmp_path, fake):
    clients: list[TestClient] = []

    def _make(extractor=None, **cfg) -> TestClient:
        ex = extractor or fake
        config = AppConfig(data_dir=tmp_path / "data", token=TOKEN, **cfg)
        app = create_app(config, extractor_provider=lambda kind: ex)
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        return client

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


@pytest.fixture
def client(make_app) -> TestClient:
    return make_app()


def put_settings(client, **notes_repo):
    s = client.get("/settings", headers=H).json()
    s["notes_repo"].update(notes_repo)
    return client.put("/settings", headers=H, json=s)


def connect(client, remote: Path):
    r = put_settings(client, remote_url=str(remote))
    assert r.status_code == 200, r.text
    r = client.post("/repo/connect", headers=H)
    assert r.status_code == 200, r.text
    return r


def repo_path(client) -> Path:
    return Path(client.get("/health", headers=H).json()["repo"]["path"])


# --- settings -------------------------------------------------------------------


def test_get_settings_returns_defaults(client):
    r = client.get("/settings", headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body["notes_repo"]["branch"] == "main"
    assert body["notes_repo"]["books_dir"] == "books"
    assert body["batches"] == {"expiry_days": 30, "warn_days_before": 7}
    assert body["extractor"]["timeout_s"] == 180
    assert body["remote_url_has_credentials"] is False


def test_put_settings_persists(client):
    r = put_settings(client, remote_url="git@github.com:me/notes.git", branch="notes")
    assert r.status_code == 200
    again = client.get("/settings", headers=H).json()
    assert again["notes_repo"]["remote_url"] == "git@github.com:me/notes.git"
    assert again["notes_repo"]["branch"] == "notes"


@pytest.mark.parametrize(
    "section,field,value",
    [
        ("notes_repo", "books_dir", ""),
        ("notes_repo", "books_dir", "/etc"),
        ("notes_repo", "books_dir", "../outside"),
        ("notes_repo", "books_dir", "a/../../b"),
        ("notes_repo", "books_dir", "-rf"),
        ("notes_repo", "branch", "-x"),
        ("notes_repo", "branch", "a b"),
        ("notes_repo", "branch", "a..b"),
        ("notes_repo", "branch", "a~1"),
        ("notes_repo", "branch", "a:b"),
        ("notes_repo", "branch", "a\x01b"),
        ("notes_repo", "branch", ""),
        ("notes_repo", "remote_url", "-uhack"),
        ("notes_repo", "remote_url", "ext::sh -c touch% /tmp/pwned"),
        ("extractor", "timeout_s", 0),
        ("extractor", "timeout_s", 3601),
        ("extractor", "concurrency", 0),
        ("extractor", "concurrency", 5),
        ("batches", "expiry_days", 0),
        ("batches", "warn_days_before", -1),
    ],
)
def test_put_settings_rejects_unsafe_values(client, section, field, value):
    s = client.get("/settings", headers=H).json()
    s[section][field] = value
    r = client.put("/settings", headers=H, json=s)
    assert r.status_code == 422, (field, value)
    assert error_code(r) == "invalid_settings"
    # Nothing was saved.
    assert client.get("/settings", headers=H).json()[section][field] != value


def test_put_settings_rejects_non_http_ollama_url(client):
    s = client.get("/settings", headers=H).json()
    s["extractor"]["ollama"]["base_url"] = "file:///etc/passwd"
    r = client.put("/settings", headers=H, json=s)
    assert r.status_code == 422
    assert error_code(r) == "invalid_settings"


def test_settings_mask_remote_credentials(client):
    r = put_settings(client, remote_url="https://me:ghp_TOKEN@github.com/me/notes.git")
    assert "ghp_TOKEN" not in r.text
    got = client.get("/settings", headers=H)
    assert "ghp_TOKEN" not in got.text
    body = got.json()
    assert body["notes_repo"]["remote_url"] == "https://***@github.com/me/notes.git"
    assert body["remote_url_has_credentials"] is True

    # Sending the masked value back (e.g. saving another field) keeps the real one.
    body["notes_repo"]["branch"] = "notes"
    assert client.put("/settings", headers=H, json=body).status_code == 200
    stored = json.loads((Path(client.app.state.services.paths.settings_file)).read_text())
    assert stored["notes_repo"]["remote_url"] == "https://me:ghp_TOKEN@github.com/me/notes.git"
    assert stored["notes_repo"]["branch"] == "notes"


# --- health & repo --------------------------------------------------------------


def test_health_before_connect(client):
    r = client.get("/health", headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body["extractor"] == {"kind": "ollama", "ok": True, "detail": "ok"}
    assert body["repo"]["cloned"] is False
    assert body["remote"]["ok"] is False


def test_health_reports_unhealthy_extractor(make_app):
    client = make_app(extractor=FakeExtractor(healthy=False))
    body = client.get("/health", headers=H).json()
    assert body["extractor"]["ok"] is False
    assert body["extractor"]["detail"] == "fake extractor is down"


def test_repo_connect_then_health_reports_cloned(client, bare_remote):
    connect(client, bare_remote)
    body = client.get("/health", headers=H).json()
    assert body["repo"]["cloned"] is True
    assert body["repo"]["dirty"] is False
    assert body["remote"] == {"ok": True, "detail": "ok"}
    assert (Path(body["repo"]["path"]) / "README.md").exists()


def test_repo_connect_bad_remote_is_400_with_stderr(client, tmp_path):
    put_settings(client, remote_url=str(tmp_path / "missing.git"))
    r = client.post("/repo/connect", headers=H)
    assert r.status_code == 400
    assert error_code(r) == "git_failed"
    assert r.json()["error"]["message"]  # git's stderr, for the user to act on


def test_repo_connect_masks_credentials_in_stderr(client):
    put_settings(client, remote_url="https://me:ghp_TOKEN@127.0.0.1:1/me/notes.git")
    r = client.post("/repo/connect", headers=H)
    assert r.status_code == 400
    assert "ghp_TOKEN" not in r.text
    assert "ghp_TOKEN" not in client.get("/health", headers=H).text


def test_janitor_run_endpoint(client):
    r = client.post("/janitor/run", headers=H)
    assert r.status_code == 200
    assert r.json() == {"warned": [], "deleted": []}


# --- books ----------------------------------------------------------------------


def test_books_create_pending_then_listed_with_flag(client):
    r = client.post("/books", headers=H, json={"title": "Permutation City", "author": "Greg Egan", "kind": "fiction"})
    assert r.status_code == 200
    assert r.json() == {
        "slug": "permutation-city", "title": "Permutation City", "author": "Greg Egan",
        "kind": "fiction", "pending": True,
    }
    books = client.get("/books", headers=H).json()
    assert [b["slug"] for b in books] == ["permutation-city"]
    assert books[0]["pending"] is True


def test_books_create_collision_returns_existing(client):
    first = client.post("/books", headers=H, json={"title": "Dune", "kind": "fiction"}).json()
    again = client.post("/books", headers=H, json={"title": "dune!", "author": "X", "kind": "non-fiction"})
    assert again.status_code == 200
    assert again.json() == first
    assert len(client.get("/books", headers=H).json()) == 1


@pytest.mark.parametrize(
    "body", [{"title": "  ", "kind": "fiction"}, {"title": "Dune", "kind": "poetry"}, {"kind": "fiction"}]
)
def test_books_create_validates_body(client, body):
    r = client.post("/books", headers=H, json=body)
    assert r.status_code == 422
    assert error_code(r) == "invalid_request"


def test_books_list_pulls_books_pushed_elsewhere(client, bare_remote, tmp_path):
    connect(client, bare_remote)
    other = tmp_path / "other"
    subprocess.run(["git", "clone", str(bare_remote), str(other)], check=True, capture_output=True)
    (other / "books").mkdir()
    (other / "books" / "dune.md").write_text("---\ntitle: Dune\nkind: fiction\n---\n")
    subprocess.run(["git", "-C", str(other), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(other), "commit", "-m", "dune"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(other), "push", "origin", "main"], check=True, capture_output=True)

    books = client.get("/books", headers=H).json()
    assert [(b["slug"], b["pending"]) for b in books] == [("dune", False)]


def test_books_list_survives_unreachable_remote(client, bare_remote):
    connect(client, bare_remote)
    client.post("/books", headers=H, json={"title": "Dune", "kind": "fiction"})
    put_settings(client, remote_url="/nonexistent/remote.git")
    subprocess.run(["git", "-C", str(repo_path(client)), "remote", "set-url", "origin", "/nonexistent/remote.git"], check=True)
    r = client.get("/books", headers=H)
    assert r.status_code == 200
    assert [b["slug"] for b in r.json()] == ["dune"]


# --- batches --------------------------------------------------------------------


def test_create_and_get_batch(client):
    r = client.post("/batches", headers=H, json={})
    assert r.status_code == 200
    batch = r.json()
    assert batch["default_book_slug"] is None
    assert batch["status"] == "open"
    assert batch["captures"] == []
    got = client.get(f"/batches/{batch['id']}", headers=H)
    assert got.status_code == 200
    assert got.json()["id"] == batch["id"]
    assert "expires_at" in got.json() and "expiring_soon" in got.json()


def test_create_batch_with_unknown_book_is_422(client):
    r = client.post("/batches", headers=H, json={"default_book_slug": "nope"})
    assert r.status_code == 422
    assert error_code(r) == "unknown_book"


def test_create_batch_with_pending_book(client):
    client.post("/books", headers=H, json={"title": "Dune", "kind": "fiction"})
    r = client.post("/batches", headers=H, json={"default_book_slug": "dune"})
    assert r.status_code == 200
    assert r.json()["default_book_slug"] == "dune"


@pytest.mark.parametrize("bad_id", ["nope", "01ARZ3NDEKTSV4RRFFQ69G5FAV", "..%2F..%2Fetc"])
def test_unknown_or_invalid_batch_is_404(client, bad_id):
    for method in ("get", "delete"):
        r = getattr(client, method)(f"/batches/{bad_id}", headers=H)
        assert r.status_code == 404, (method, bad_id)
        # An encoded slash decodes to a path no route matches: a plain not_found.
        assert error_code(r) in ("batch_not_found", "not_found")
    r = client.patch(f"/batches/{bad_id}", headers=H, json={"default_book_slug": None})
    assert r.status_code == 404


def test_patch_batch_default_book(client):
    client.post("/books", headers=H, json={"title": "Dune", "kind": "fiction"})
    b = client.post("/batches", headers=H, json={}).json()
    r = client.patch(f"/batches/{b['id']}", headers=H, json={"default_book_slug": "dune"})
    assert r.status_code == 200
    assert r.json()["default_book_slug"] == "dune"
    assert r.json()["updated_at"] > b["updated_at"]
    bad = client.patch(f"/batches/{b['id']}", headers=H, json={"default_book_slug": "../x"})
    assert bad.status_code == 422
    cleared = client.patch(f"/batches/{b['id']}", headers=H, json={"default_book_slug": None})
    assert cleared.json()["default_book_slug"] is None


def test_patch_batch_ignores_other_fields(client):
    b = client.post("/batches", headers=H, json={}).json()
    r = client.patch(f"/batches/{b['id']}", headers=H, json={"status": "pushed", "captures": []})
    assert r.status_code == 422


def test_delete_batch_removes_folder(client):
    b = client.post("/batches", headers=H, json={}).json()
    folder = client.app.state.services.paths.batch_dir(b["id"])
    assert folder.exists()
    r = client.delete(f"/batches/{b['id']}", headers=H)
    assert r.status_code == 204
    assert not folder.exists()
    assert client.get(f"/batches/{b['id']}", headers=H).status_code == 404


def test_list_batches_includes_expiry_fields(client):
    b = client.post("/batches", headers=H, json={}).json()
    client.post(f"/batches/{b['id']}/captures", headers=H, json={"source": "kindle", "highlights": [{"text": "x"}]})
    listed = client.get("/batches", headers=H).json()
    assert len(listed) == 1
    item = listed[0]
    assert {"id", "default_book_slug", "created_at", "updated_at", "expires_at", "expiring_soon", "warned_at", "counts"} <= set(item)
    assert item["expiring_soon"] is False
    assert item["warned_at"] is None
    assert item["counts"]["ready"] == 1
    assert item["counts"]["pending"] == 0
    assert "captures" not in item


def test_list_batches_flags_expiring_soon(client):
    svc = client.app.state.services
    b = client.post("/batches", headers=H, json={}).json()

    def age(batch):
        batch.updated_at = batch.updated_at - timedelta(days=25)

    svc.store.modify(b["id"], age, touch=False)
    item = client.get("/batches", headers=H).json()[0]
    assert item["expiring_soon"] is True


def _set_pushing(client, batch_id):
    def change(b):
        b.status = BatchStatus.pushing

    client.app.state.services.store.modify(batch_id, change, touch=False)


def test_batch_edits_refused_while_pushing(client):
    b = client.post("/batches", headers=H, json={}).json()
    _set_pushing(client, b["id"])
    r = client.patch(f"/batches/{b['id']}", headers=H, json={"default_book_slug": None})
    assert r.status_code == 409
    assert error_code(r) == "batch_pushing"
    r = client.delete(f"/batches/{b['id']}", headers=H)
    assert r.status_code == 409
    assert error_code(r) == "batch_pushing"
    assert client.get(f"/batches/{b['id']}", headers=H).status_code == 200


# --- captures -------------------------------------------------------------------


def new_batch(client, **body) -> str:
    return client.post("/batches", headers=H, json=body).json()["id"]


def upload(client, batch_id, *paths):
    files = [("files", (p.name, p.read_bytes(), "application/octet-stream")) for p in paths]
    return client.post(f"/batches/{batch_id}/captures", headers=H, files=files)


def get_capture(client, batch_id, capture_id) -> dict:
    batch = client.get(f"/batches/{batch_id}", headers=H).json()
    return next(c for c in batch["captures"] if c["id"] == capture_id)


def wait_status(client, batch_id, capture_id, status, timeout=2.0) -> dict:
    wait_until(lambda: get_capture(client, batch_id, capture_id)["status"] == status, timeout)
    return get_capture(client, batch_id, capture_id)


def kindle(client, batch_id, texts=("a passage",), **extra) -> dict:
    body = {"source": "kindle", "highlights": [{"text": t} for t in texts], **extra}
    r = client.post(f"/batches/{batch_id}/captures", headers=H, json=body)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def gif(tmp_path):
    from PIL import Image

    p = tmp_path / "anim.gif"
    Image.new("RGB", (10, 10), "white").save(p, "GIF")
    return p


def test_create_batch_upload_png_and_reject_gif(client, make_image, gif):
    b = new_batch(client)
    r = upload(client, b, make_image("page.png"), gif)
    assert r.status_code == 200
    body = r.json()
    assert len(body["created"]) == 1
    created = body["created"][0]
    assert created["source"] == "photo"
    assert created["image_file"].endswith(".png")
    assert body["rejected"] == [{"filename": "anim.gif", "reason": "unsupported_type"}]


def test_upload_rejects_duplicate_photo(client, make_image):
    b = new_batch(client)
    p = make_image("page.png")
    upload(client, b, p)
    r = upload(client, b, p)
    assert r.json()["created"] == []
    assert r.json()["rejected"] == [{"filename": "page.png", "reason": "duplicate"}]


def test_upload_rejects_oversize_file_without_failing_others(make_app, make_image):
    client = make_app(max_upload_bytes=50_000)
    b = new_batch(client)
    small = make_image("small.png")
    big = small.parent / "big.png"
    big.write_bytes(small.read_bytes() + b"\0" * 60_000)
    r = upload(client, b, big, small)
    assert r.status_code == 200
    assert [c["image_file"].endswith(".png") for c in r.json()["created"]] == [True]
    assert r.json()["rejected"] == [{"filename": "big.png", "reason": "too_large"}]


def test_upload_rejects_files_beyond_the_per_request_limit(make_app, make_image):
    # Files are ingested as they stream in, so the extras are rejected individually
    # rather than failing (and un-doing) the ones already stored.
    client = make_app(max_upload_files=2)
    b = new_batch(client)
    paths = [make_image(f"p{i}.png", highlight_text=f"text {i}") for i in range(3)]
    r = upload(client, b, *paths)
    assert r.status_code == 200
    assert len(r.json()["created"]) == 2
    assert r.json()["rejected"] == [{"filename": "p2.png", "reason": "too_many_files"}]


def test_upload_refuses_oversize_request_up_front(make_app, make_image):
    client = make_app(max_upload_files=1, max_upload_bytes=1000)
    b = new_batch(client)
    big = make_image("p.png")
    big.write_bytes(big.read_bytes() + b"\0" * 3_000_000)
    r = upload(client, b, big)
    assert r.status_code == 413
    assert error_code(r) == "payload_too_large"


def test_upload_malformed_multipart_is_400(client):
    b = new_batch(client)
    r = client.post(
        f"/batches/{b}/captures", headers={**H, "Content-Type": "multipart/form-data"}, content=b"junk"
    )
    assert r.status_code == 400
    assert error_code(r) == "invalid_upload"


def test_upload_to_unknown_batch_is_404(client, make_image):
    r = upload(client, "01ARZ3NDEKTSV4RRFFQ69G5FAV", make_image("page.png"))
    assert r.status_code == 404


def test_upload_runs_extraction_to_ready(client, make_image):
    b = new_batch(client)
    cid = upload(client, b, make_image("page.png")).json()["created"][0]["id"]
    c = wait_status(client, b, cid, "ready")
    assert [h["text"] for h in c["highlights"]] == ["mathematical possibility"]
    assert c["extractor_used"] == "fake"


def test_kindle_capture_starts_ready(client):
    client.post("/books", headers=H, json={"title": "Dune", "kind": "fiction"})
    b = new_batch(client)
    c = kindle(client, b, texts=("fear is the mind-killer",), book_slug="dune", page=12)
    assert c["source"] == "kindle"
    assert c["status"] == "ready"
    assert c["image_file"] is None
    assert c["book_slug"] == "dune"
    assert c["page"] == 12
    assert [h["text"] for h in c["highlights"]] == ["fear is the mind-killer"]


def test_kindle_capture_validates_body(client):
    b = new_batch(client)
    r = client.post(f"/batches/{b}/captures", headers=H, json={"source": "kindle", "highlights": [{"text": "x"}], "book_slug": "../etc"})
    assert r.status_code == 422
    assert error_code(r) == "unknown_book"
    r = client.post(f"/batches/{b}/captures", headers=H, json={"source": "photo", "highlights": []})
    assert r.status_code == 422
    r = client.post(f"/batches/{b}/captures", headers=H, json={"source": "kindle", "highlights": [{"text": "x"}], "image_file": "../../x"})
    assert r.status_code == 422


def test_approve_requires_text_and_book(client):
    b = new_batch(client)
    empty = kindle(client, b, texts=("   ",))
    r = client.patch(f"/captures/{empty['id']}", headers=H, json={"status": "approved"})
    assert r.status_code == 422
    assert error_code(r) == "not_approvable"

    no_book = kindle(client, b, texts=("real text",))
    r = client.patch(f"/captures/{no_book['id']}", headers=H, json={"status": "approved"})
    assert r.status_code == 422
    assert error_code(r) == "not_approvable"

    client.post("/books", headers=H, json={"title": "Dune", "kind": "fiction"})
    client.patch(f"/batches/{b}", headers=H, json={"default_book_slug": "dune"})
    r = client.patch(f"/captures/{no_book['id']}", headers=H, json={"status": "approved"})
    assert r.status_code == 200
    assert r.json()["status"] == "approved"


def test_editing_approved_capture_to_empty_is_refused(client):
    client.post("/books", headers=H, json={"title": "Dune", "kind": "fiction"})
    b = new_batch(client, default_book_slug="dune")
    c = kindle(client, b)
    client.patch(f"/captures/{c['id']}", headers=H, json={"status": "approved"})
    r = client.patch(f"/captures/{c['id']}", headers=H, json={"highlights": []})
    assert r.status_code == 422
    assert error_code(r) == "not_approvable"


def test_patch_touches_updated_at(client):
    b = new_batch(client)
    c = kindle(client, b)
    before = client.get(f"/batches/{b}", headers=H).json()["updated_at"]
    time.sleep(0.01)
    r = client.patch(f"/captures/{c['id']}", headers=H, json={"chapter": "Chapter 1"})
    assert r.status_code == 200
    assert r.json()["chapter"] == "Chapter 1"
    assert client.get(f"/batches/{b}", headers=H).json()["updated_at"] > before


def test_patch_edits_fields(client):
    client.post("/books", headers=H, json={"title": "Dune", "kind": "fiction"})
    b = new_batch(client)
    c = kindle(client, b)
    r = client.patch(
        f"/captures/{c['id']}", headers=H,
        json={"page": 163, "book_slug": "dune", "captured_at": "2026-11-08T21:14:00+00:00"},
    )
    assert r.status_code == 200
    body = r.json()
    assert (body["page"], body["book_slug"]) == (163, "dune")
    assert body["captured_at"].startswith("2026-11-08T21:14:00")
    r = client.patch(f"/captures/{c['id']}", headers=H, json={"book_slug": "nope"})
    assert r.status_code == 422
    assert error_code(r) == "unknown_book"


def test_patch_keeps_known_highlight_ids_and_mints_new_ones(client):
    b = new_batch(client)
    c = kindle(client, b, texts=("one",))
    hid = c["highlights"][0]["id"]
    r = client.patch(
        f"/captures/{c['id']}", headers=H,
        json={"highlights": [
            {"id": hid, "text": "one, fixed", "note": "mine"},
            {"id": "x --> <script>", "text": "two"},
            {"text": "three"},
        ]},
    )
    assert r.status_code == 200
    hs = r.json()["highlights"]
    assert hs[0] == {"id": hid, "text": "one, fixed", "note": "mine"}
    # Ids end up in markdown markers, so only ids we minted are ever kept.
    assert hs[1]["id"] != "x --> <script>" and hs[1]["text"] == "two"
    assert len({h["id"] for h in hs}) == 3


@pytest.mark.parametrize(
    "field,value",
    [("image_file", "../../etc/passwd"), ("image_sha256", "x"), ("id", "X"), ("source", "photo"), ("error", "x")],
)
def test_patch_cannot_set_protected_fields(client, field, value):
    b = new_batch(client)
    c = kindle(client, b)
    r = client.patch(f"/captures/{c['id']}", headers=H, json={field: value})
    assert r.status_code == 422
    assert get_capture(client, b, c["id"])[field] == c[field]


def test_patch_rotation_validates_and_image_endpoint_serves_rotated(client, make_image):
    from io import BytesIO

    from PIL import Image

    b = new_batch(client)
    cid = upload(client, b, make_image("page.png")).json()["created"][0]["id"]
    wait_status(client, b, cid, "ready")
    r = client.patch(f"/captures/{cid}", headers=H, json={"rotation": 45})
    assert r.status_code == 422

    img = client.get(f"/captures/{cid}/image", headers=H)
    assert img.status_code == 200
    assert img.headers["content-type"] == "image/jpeg"
    assert Image.open(BytesIO(img.content)).size == (600, 200)

    r = client.patch(f"/captures/{cid}", headers=H, json={"rotation": 90})
    assert r.status_code == 200
    assert r.json()["rotation"] == 90
    img = client.get(f"/captures/{cid}/image", headers=H)
    assert Image.open(BytesIO(img.content)).size == (200, 600)


def test_image_for_kindle_or_unknown_capture_is_404(client):
    b = new_batch(client)
    c = kindle(client, b)
    r = client.get(f"/captures/{c['id']}/image", headers=H)
    assert r.status_code == 404
    r = client.get("/captures/01ARZ3NDEKTSV4RRFFQ69G5FAV/image", headers=H)
    assert r.status_code == 404
    assert error_code(r) == "capture_not_found"


def test_status_transitions_follow_state_machine(client):
    client.post("/books", headers=H, json={"title": "Dune", "kind": "fiction"})
    b = new_batch(client, default_book_slug="dune")
    c = kindle(client, b)
    url = f"/captures/{c['id']}"
    assert client.patch(url, headers=H, json={"status": "approved"}).json()["status"] == "approved"
    assert client.patch(url, headers=H, json={"status": "ready"}).json()["status"] == "ready"
    assert client.patch(url, headers=H, json={"status": "discarded"}).json()["status"] == "discarded"
    for target in ("approved", "pushed", "pending", "extracting", "failed"):
        r = client.patch(url, headers=H, json={"status": target})
        assert r.status_code == 409, target
        assert error_code(r) == "invalid_transition"


def test_failed_capture_can_be_fixed_by_hand_or_retried(make_app, make_image):
    kinds = []
    broken = FakeExtractor(error="model exploded")

    def provider(kind):
        kinds.append(kind)
        return broken

    config = AppConfig(data_dir=make_image("x.png").parent / "data2", token=TOKEN)
    with TestClient(create_app(config, extractor_provider=provider)) as client:
        b = new_batch(client)
        cid = upload(client, b, make_image("page.png")).json()["created"][0]["id"]
        c = wait_status(client, b, cid, "failed")
        assert c["error"] == "model exploded"

        broken.error = None
        broken.result = ExtractionResult(highlights=[ExtractedHighlight(text="second try")])
        kinds.clear()
        r = client.post(f"/captures/{cid}/retry", headers=H, json={"extractor": "tesseract"})
        assert r.status_code == 200
        assert r.json()["status"] == "pending"
        c = wait_status(client, b, cid, "ready")
        assert [h["text"] for h in c["highlights"]] == ["second try"]
        assert "tesseract" in kinds

        # A ready capture can't be retried (it would overwrite the user's edits).
        r = client.post(f"/captures/{cid}/retry", headers=H, json={})
        assert r.status_code == 409
        assert error_code(r) == "invalid_transition"

        broken.error = "again"
        b2 = new_batch(client)
        cid2 = upload(client, b2, make_image("page2.png", highlight_text="other")).json()["created"][0]["id"]
        wait_status(client, b2, cid2, "failed")
        r = client.patch(f"/captures/{cid2}", headers=H, json={"status": "ready", "highlights": [{"text": "typed"}]})
        assert r.status_code == 200
        assert r.json()["status"] == "ready"
        assert r.json()["error"] is None


def test_retry_kindle_capture_is_refused(client):
    b = new_batch(client)
    c = kindle(client, b)
    r = client.post(f"/captures/{c['id']}/retry", headers=H, json={})
    assert r.status_code == 409
    r = client.post(f"/captures/{c['id']}/retry", headers=H, json={"extractor": "gpt"})
    assert r.status_code == 422


def test_delete_capture_removes_photo(client, make_image):
    b = new_batch(client)
    cap = upload(client, b, make_image("page.png")).json()["created"][0]
    svc = client.app.state.services
    photo = svc.paths.photos_dir(b) / cap["image_file"]
    assert photo.exists()
    r = client.delete(f"/captures/{cap['id']}", headers=H)
    assert r.status_code == 204
    assert not photo.exists()
    assert client.get(f"/batches/{b}", headers=H).json()["captures"] == []
    r = client.delete(f"/captures/{cap['id']}", headers=H)
    assert r.status_code == 404
    assert error_code(r) == "capture_not_found"


def test_capture_edits_refused_while_pushing(client):
    b = new_batch(client)
    c = kindle(client, b)
    _set_pushing(client, b)
    for resp in (
        client.patch(f"/captures/{c['id']}", headers=H, json={"chapter": "x"}),
        client.delete(f"/captures/{c['id']}", headers=H),
        client.post(f"/captures/{c['id']}/retry", headers=H, json={}),
    ):
        assert resp.status_code == 409
        assert error_code(resp) == "batch_pushing"
    assert get_capture(client, b, c["id"])["chapter"] is None


# --- push -----------------------------------------------------------------------


def test_full_flow_push_deletes_batch(client, bare_remote, make_image):
    connect(client, bare_remote)
    book = client.post("/books", headers=H, json={"title": "Permutation City", "author": "Greg Egan", "kind": "fiction"}).json()
    b = new_batch(client, default_book_slug=book["slug"])
    cid = upload(client, b, make_image("p163.png")).json()["created"][0]["id"]
    wait_status(client, b, cid, "ready")
    assert client.patch(f"/captures/{cid}", headers=H, json={"status": "approved"}).status_code == 200

    r = client.post(f"/batches/{b}/push", headers=H)
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["files_changed"] == ["books/permutation-city.md"]
    assert result["highlights_written"] == 1
    assert result["batch_deleted"] is True
    assert len(result["commit_sha"]) == 40

    assert client.get(f"/batches/{b}", headers=H).status_code == 404
    text = remote_text(bare_remote, "books/permutation-city.md")
    assert text and "mathematical possibility" in text
    # The pending book became a real one.
    assert client.get("/books", headers=H).json()[0]["pending"] is False


def test_push_dirty_repo_409(client, bare_remote):
    connect(client, bare_remote)
    (repo_path(client) / "books").mkdir()
    (repo_path(client) / "books" / "stray.md").write_text("mine\n")
    b = new_batch(client)
    r = client.post(f"/batches/{b}/push", headers=H)
    assert r.status_code == 409
    assert error_code(r) == "dirty_repo"


def test_push_not_cloned_409_without_path(client, tmp_path):
    b = new_batch(client)
    r = client.post(f"/batches/{b}/push", headers=H)
    assert r.status_code == 409
    assert error_code(r) == "not_cloned"
    assert str(tmp_path) not in r.text


def test_push_nothing_to_push_400(client, bare_remote):
    connect(client, bare_remote)
    b = new_batch(client)
    kindle(client, b)
    r = client.post(f"/batches/{b}/push", headers=H)
    assert r.status_code == 400
    assert error_code(r) == "nothing_to_push"


def test_push_git_failure_502_masks_credentials(client, bare_remote):
    connect(client, bare_remote)
    client.post("/books", headers=H, json={"title": "Dune", "kind": "fiction"})
    b = new_batch(client, default_book_slug="dune")
    c = kindle(client, b)
    client.patch(f"/captures/{c['id']}", headers=H, json={"status": "approved"})
    bad = "https://me:ghp_TOKEN@127.0.0.1:1/me/notes.git"
    subprocess.run(["git", "-C", str(repo_path(client)), "remote", "set-url", "origin", bad], check=True)
    r = client.post(f"/batches/{b}/push", headers=H)
    assert r.status_code == 502
    assert error_code(r) == "git_failed"
    assert "ghp_TOKEN" not in r.text
    # The batch is kept and editable again.
    assert client.get(f"/batches/{b}", headers=H).json()["status"] == "open"


def test_push_unknown_batch_404(client):
    r = client.post("/batches/01ARZ3NDEKTSV4RRFFQ69G5FAV/push", headers=H)
    assert r.status_code == 404


# --- events ---------------------------------------------------------------------


def read_sse(resp, want: int = 1, comments: bool = False, timeout=3.0) -> list[dict]:
    """Collect `want` SSE events (or comment lines) from a streaming response."""
    events, current = [], {}
    deadline = time.monotonic() + timeout
    for line in resp.iter_lines():
        if time.monotonic() > deadline:
            break
        if comments and line.startswith(":"):
            events.append({"comment": line})
        elif line.startswith("event:"):
            current["event"] = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            current["data"] = json.loads(line.split(":", 1)[1].strip())
        elif line == "" and current:
            events.append(current)
            current = {}
        if len(events) >= want:
            break
    return events


def subscribers(client, batch_id) -> int:
    return len(client.app.state.services.events._subs.get(batch_id, []))


def test_events_stream_emits_status_changed(client, make_image):
    b = new_batch(client)
    got: list[dict] = []

    def listen():
        with client.stream("GET", f"/batches/{b}/events?token={TOKEN}") as resp:
            assert resp.status_code == 200
            got.extend(read_sse(resp))

    t = threading.Thread(target=listen, daemon=True)
    t.start()
    wait_until(lambda: subscribers(client, b) == 1)
    upload(client, b, make_image("page.png"))
    t.join(5)
    assert got and got[0]["event"] == "capture.status_changed"
    assert got[0]["data"]["status"] == "extracting"


def test_events_heartbeat_and_unsubscribe_on_disconnect(make_app):
    client = make_app(sse_heartbeat_s=0.1)
    b = new_batch(client)
    with client.stream("GET", f"/batches/{b}/events", headers=H) as resp:
        wait_until(lambda: subscribers(client, b) == 1)
        beats = read_sse(resp, comments=True)
        assert beats and beats[0]["comment"].startswith(": ping")
    wait_until(lambda: subscribers(client, b) == 0)


def test_events_unknown_batch_404(client):
    r = client.get("/batches/01ARZ3NDEKTSV4RRFFQ69G5FAV/events", headers=H)
    assert r.status_code == 404


# --- auth, CORS, error shape ----------------------------------------------------


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


# --- lifespan & CLI -------------------------------------------------------------


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
