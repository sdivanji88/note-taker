import json
from pathlib import Path

import pytest
from api_helpers import (
    H,
    connect,
    error_code,
    put_settings,
)

from note_taker.extractors.fake import FakeExtractor

# Tesseract isn't installed here; rotation guessing must be inert and fast.
pytestmark = pytest.mark.usefixtures("no_osd")


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
