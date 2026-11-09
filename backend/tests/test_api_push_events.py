import subprocess
import threading

import pytest
from api_helpers import (
    TOKEN,
    H,
    connect,
    error_code,
    kindle,
    new_batch,
    read_sse,
    remote_text,
    repo_path,
    subscribers,
    upload,
    wait_status,
    wait_until,
)

# Tesseract isn't installed here; rotation guessing must be inert and fast.
pytestmark = pytest.mark.usefixtures("no_osd")


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
