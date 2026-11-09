import subprocess
from datetime import timedelta

import pytest
from api_helpers import (
    H,
    _set_pushing,
    connect,
    error_code,
    put_settings,
    repo_path,
)

# Tesseract isn't installed here; rotation guessing must be inert and fast.
pytestmark = pytest.mark.usefixtures("no_osd")


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
