import time

import pytest
from api_helpers import (
    FIELD_EDITS,
    TOKEN,
    GateExtractor,
    H,
    _set_pushing,
    error_code,
    get_capture,
    kindle,
    new_batch,
    upload,
    wait_status,
)
from fastapi.testclient import TestClient

from note_taker.api.app import AppConfig, create_app
from note_taker.extractors.fake import FakeExtractor
from note_taker.models import ExtractedHighlight, ExtractionResult

# Tesseract isn't installed here; rotation guessing must be inert and fast.
pytestmark = pytest.mark.usefixtures("no_osd")


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


@pytest.mark.parametrize("edit", FIELD_EDITS)
def test_edits_refused_while_pending(make_app, make_image, edit):
    client = make_app(extractor=FakeExtractor(healthy=False))
    client.post("/books", headers=H, json={"title": "Dune", "kind": "fiction"})
    b = new_batch(client)
    cid = upload(client, b, make_image("page.png")).json()["created"][0]["id"]
    before = get_capture(client, b, cid)
    assert before["status"] == "pending"
    r = client.patch(f"/captures/{cid}", headers=H, json=edit)
    assert r.status_code == 409, edit
    assert error_code(r) == "invalid_transition"
    after = get_capture(client, b, cid)
    assert {k: after[k] for k in edit} == {k: before[k] for k in edit}


@pytest.mark.parametrize("edit", FIELD_EDITS)
def test_edits_refused_while_extracting_and_result_lands(make_app, make_image, edit):
    gate = GateExtractor(result=ExtractionResult(highlights=[ExtractedHighlight(text="from the model")]))
    client = make_app(extractor=gate)
    client.post("/books", headers=H, json={"title": "Dune", "kind": "fiction"})
    b = new_batch(client)
    cid = upload(client, b, make_image("page.png")).json()["created"][0]["id"]
    assert gate.started.wait(2)
    before = wait_status(client, b, cid, "extracting")
    r = client.patch(f"/captures/{cid}", headers=H, json=edit)
    assert r.status_code == 409, edit
    assert error_code(r) == "invalid_transition"
    after = get_capture(client, b, cid)
    assert {k: after[k] for k in edit} == {k: before[k] for k in edit}
    gate.release.set()
    c = wait_status(client, b, cid, "ready")
    assert [h["text"] for h in c["highlights"]] == ["from the model"]


def test_discard_allowed_while_pending(make_app, make_image):
    client = make_app(extractor=FakeExtractor(healthy=False))
    b = new_batch(client)
    cid = upload(client, b, make_image("page.png")).json()["created"][0]["id"]
    r = client.patch(f"/captures/{cid}", headers=H, json={"status": "discarded"})
    assert r.status_code == 200
    assert r.json()["status"] == "discarded"


def test_discard_allowed_while_extracting_and_result_dropped(make_app, make_image):
    gate = GateExtractor(result=ExtractionResult(highlights=[ExtractedHighlight(text="late")]))
    client = make_app(extractor=gate)
    b = new_batch(client)
    cid = upload(client, b, make_image("page.png")).json()["created"][0]["id"]
    assert gate.started.wait(2)
    wait_status(client, b, cid, "extracting")
    r = client.patch(f"/captures/{cid}", headers=H, json={"status": "discarded"})
    assert r.status_code == 200
    gate.release.set()
    time.sleep(0.3)
    c = get_capture(client, b, cid)
    assert c["status"] == "discarded"
    assert c["highlights"] == []


@pytest.mark.parametrize("final", ["ready", "failed"])
def test_rotation_allowed_on_ready_and_failed(make_app, make_image, final):
    ex = FakeExtractor(error="boom") if final == "failed" else FakeExtractor()
    client = make_app(extractor=ex)
    b = new_batch(client)
    cid = upload(client, b, make_image("page.png")).json()["created"][0]["id"]
    wait_status(client, b, cid, final)
    r = client.patch(f"/captures/{cid}", headers=H, json={"rotation": 180})
    assert r.status_code == 200
    assert r.json()["rotation"] == 180
    # Rotating does not itself re-run extraction; the client retries if it wants that.
    assert r.json()["status"] == final


def test_rotation_refused_on_approved(client):
    client.post("/books", headers=H, json={"title": "Dune", "kind": "fiction"})
    b = new_batch(client, default_book_slug="dune")
    c = kindle(client, b)
    client.patch(f"/captures/{c['id']}", headers=H, json={"status": "approved"})
    r = client.patch(f"/captures/{c['id']}", headers=H, json={"rotation": 90})
    assert r.status_code == 409
    assert error_code(r) == "invalid_transition"


def test_edit_guard_reads_status_atomically_with_the_write(client, monkeypatch):
    # The route's lookup sees `ready`; extraction claims the capture before the write.
    # The guard must judge the state it is writing over, not the earlier snapshot.
    from note_taker.models import CaptureStatus

    svc = client.app.state.services
    b = new_batch(client)
    c = kindle(client, b)
    real_find = svc.store.find_capture

    def find_then_claim(capture_id):
        found = real_find(capture_id)

        def claim(batch):
            for cap in batch.captures:
                if cap.id == capture_id:
                    cap.status = CaptureStatus.extracting

        svc.store.modify(b, claim, touch=False)
        return found

    monkeypatch.setattr(svc.store, "find_capture", find_then_claim)
    r = client.patch(f"/captures/{c['id']}", headers=H, json={"highlights": [{"text": "mine"}]})
    assert r.status_code == 409
    assert error_code(r) == "invalid_transition"
    monkeypatch.undo()
    assert get_capture(client, b, c["id"])["highlights"][0]["text"] == "a passage"
