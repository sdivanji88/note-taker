"""Shared helpers for the API test modules (fixtures live in conftest.py)."""

import json
import subprocess
import threading
import time
from pathlib import Path

from note_taker.extractors.fake import FakeExtractor
from note_taker.models import BatchStatus

TOKEN = "s3cret-token"
H = {"X-Session-Token": TOKEN}


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


def _set_pushing(client, batch_id):
    def change(b):
        b.status = BatchStatus.pushing

    client.app.state.services.store.modify(batch_id, change, touch=False)


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


class GateExtractor(FakeExtractor):
    """Holds extract() until released, so a capture sits in `extracting` on demand."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.started = threading.Event()
        self.release = threading.Event()

    def extract(self, image_path, rotation=0):
        self.started.set()
        self.release.wait(5)
        return super().extract(image_path, rotation)


FIELD_EDITS = [
    {"highlights": [{"text": "typed by hand"}]},
    {"page": 7},
    {"book_slug": "dune"},
    {"chapter": "One"},
    {"captured_at": "2026-11-08T21:14:00+00:00"},
    {"rotation": 90},
    {"status": "approved"},
]
