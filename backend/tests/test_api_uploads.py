
import pytest
from api_helpers import (
    H,
    error_code,
    kindle,
    new_batch,
    upload,
    wait_status,
)

# Tesseract isn't installed here; rotation guessing must be inert and fast.
pytestmark = pytest.mark.usefixtures("no_osd")


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
