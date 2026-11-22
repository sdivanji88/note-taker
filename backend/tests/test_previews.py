"""Cached, downscaled previews behind GET /captures/{id}/image (and their lifecycle)."""

import io
import subprocess

import pytest
from api_helpers import H, connect, error_code, new_batch, upload, wait_status
from PIL import Image, ImageChops, ImageStat

from note_taker import imaging
from note_taker.batch_store import BatchStore

pytestmark = pytest.mark.usefixtures("no_osd")


def _decode(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


def _add(store: BatchStore, path, batch_id=None):
    batch_id = batch_id or store.create(None).id
    return batch_id, store.add_photo(batch_id, path.name, path.read_bytes())


def _set_rotation(store, batch_id, capture, rotation):
    def change(b):
        for c in b.captures:
            if c.id == capture.id:
                c.rotation = rotation

    return next(c for c in store.modify(batch_id, change).captures if c.id == capture.id)


def _previews(paths, batch_id):
    folder = paths.previews_dir(batch_id)
    return sorted(p.name for p in folder.glob("*.jpg")) if folder.exists() else []


@pytest.fixture
def store(data_paths):
    return BatchStore(data_paths)


@pytest.fixture
def spy(monkeypatch):
    """Records every real decode+encode the store asks imaging for."""
    calls = []
    real = imaging.downscaled_jpeg_bytes

    def wrapper(*args, **kwargs):
        calls.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(imaging, "downscaled_jpeg_bytes", wrapper)
    return calls


# --- BatchStore ------------------------------------------------------------------


def test_preview_is_downscaled_to_max_edge(store, tmp_path):
    big = tmp_path / "big.png"
    Image.new("RGB", (4000, 1000), "white").save(big)
    batch_id, cap = _add(store, big)
    img = _decode(store.preview_jpeg(batch_id, cap))
    assert img.format == "JPEG"
    assert img.size == (2000, 500)


def test_preview_applies_exif_orientation(store, make_image):
    batch_id, cap = _add(store, make_image("o.jpg", fmt="JPEG", exif_orientation=6))
    assert _decode(store.preview_jpeg(batch_id, cap)).size == (200, 600)


def test_preview_applies_capture_rotation_like_load_upright(store, make_image):
    upright = Image.open(make_image("up.png")).convert("RGB")
    batch_id, cap = _add(store, make_image("side.png", pixel_rotation=90))
    cap = _set_rotation(store, batch_id, cap, 270)
    preview = _decode(store.preview_jpeg(batch_id, cap)).convert("RGB")
    assert preview.size == upright.size
    # JPEG is lossy, so compare the picture rather than the bytes.
    assert sum(ImageStat.Stat(ImageChops.difference(preview, upright)).mean) < 8


def test_second_request_is_served_from_the_cache(store, make_image, spy, data_paths):
    batch_id, cap = _add(store, make_image("a.png"))
    first = store.preview_jpeg(batch_id, cap)
    assert _previews(data_paths, batch_id) == [f"{cap.id}-r0.jpg"]
    assert store.preview_jpeg(batch_id, cap) == first
    assert len(spy) == 1


def test_rotation_change_invalidates_the_cache_and_removes_the_old_preview(
    store, make_image, spy, data_paths
):
    batch_id, cap = _add(store, make_image("a.png"))
    store.preview_jpeg(batch_id, cap)
    turned = _set_rotation(store, batch_id, cap, 90)
    assert _decode(store.preview_jpeg(batch_id, turned)).size == (200, 600)
    assert len(spy) == 2
    assert _previews(data_paths, batch_id) == [f"{cap.id}-r90.jpg"]


def test_missing_photo_raises_file_not_found(store, make_image):
    batch_id, cap = _add(store, make_image("a.png"))
    store.photo_path(batch_id, cap).unlink()
    with pytest.raises(FileNotFoundError):
        store.preview_jpeg(batch_id, cap)


def test_drop_photo_removes_original_and_every_preview(store, make_image, data_paths):
    batch_id, cap = _add(store, make_image("a.png"))
    store.preview_jpeg(batch_id, cap)
    _, other = _add(store, make_image("b.png", highlight_text="other"), batch_id)
    store.preview_jpeg(batch_id, other)

    store.drop_photo(batch_id, cap)
    store.drop_photo(batch_id, cap)  # already gone is fine

    assert not store.photo_path(batch_id, cap).exists()
    assert _previews(data_paths, batch_id) == [f"{other.id}-r0.jpg"]
    assert store.photo_path(batch_id, other).exists()


def test_remove_capture_drops_its_preview(store, make_image, data_paths):
    batch_id, cap = _add(store, make_image("a.png"))
    store.preview_jpeg(batch_id, cap)
    store.remove_capture(batch_id, cap.id)
    assert _previews(data_paths, batch_id) == []
    assert not store.photo_path(batch_id, cap).exists()


def test_preview_is_not_resurrected_by_a_batch_deleted_mid_decode(
    store, make_image, data_paths, monkeypatch
):
    batch_id, cap = _add(store, make_image("a.png"))
    real = imaging.downscaled_jpeg_bytes

    def decode_then_batch_vanishes(*args, **kwargs):
        data = real(*args, **kwargs)
        store.delete(batch_id)  # the user discarded the batch while we were decoding
        return data

    monkeypatch.setattr(imaging, "downscaled_jpeg_bytes", decode_then_batch_vanishes)
    assert _decode(store.preview_jpeg(batch_id, cap)).size == (600, 200)  # served uncached
    assert not data_paths.batch_dir(batch_id).exists()


def test_preview_is_not_written_for_a_capture_dropped_mid_decode(
    store, make_image, data_paths, monkeypatch
):
    batch_id, cap = _add(store, make_image("a.png"))
    real = imaging.downscaled_jpeg_bytes

    def decode_then_capture_vanishes(*args, **kwargs):
        data = real(*args, **kwargs)
        store.remove_capture(batch_id, cap.id)
        return data

    monkeypatch.setattr(imaging, "downscaled_jpeg_bytes", decode_then_capture_vanishes)
    store.preview_jpeg(batch_id, cap)
    assert _previews(data_paths, batch_id) == []


# --- HTTP ------------------------------------------------------------------------


def _ready_photo(client, make_image, name="page.png"):
    b = new_batch(client)
    cid = upload(client, b, make_image(name)).json()["created"][0]["id"]
    wait_status(client, b, cid, "ready")
    return b, cid


def test_image_route_sends_cache_headers(client, make_image):
    _, cid = _ready_photo(client, make_image)
    r = client.get(f"/captures/{cid}/image", headers=H)
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.headers["etag"] == f'"{cid}-r0"'
    assert r.headers["cache-control"] == "private, no-cache"
    assert _decode(r.content).size == (600, 200)


def test_if_none_match_gets_304_without_touching_the_photo(client, make_image, monkeypatch):
    _, cid = _ready_photo(client, make_image)
    etag = client.get(f"/captures/{cid}/image", headers=H).headers["etag"]

    def forbidden(*a, **k):
        raise AssertionError("a 304 must not read or decode the photo")

    monkeypatch.setattr(client.app.state.services.store, "preview_jpeg", forbidden)
    for header in (etag, f'W/{etag}', f'"other", {etag}', "*"):
        r = client.get(f"/captures/{cid}/image", headers={**H, "If-None-Match": header})
        assert r.status_code == 304, header
        assert r.content == b""
        assert r.headers["etag"] == etag


def test_etag_changes_with_rotation(client, make_image):
    _, cid = _ready_photo(client, make_image)
    old = client.get(f"/captures/{cid}/image", headers=H).headers["etag"]
    assert client.patch(f"/captures/{cid}", headers=H, json={"rotation": 90}).status_code == 200
    r = client.get(f"/captures/{cid}/image", headers={**H, "If-None-Match": old})
    assert r.status_code == 200
    assert r.headers["etag"] == f'"{cid}-r90"' != old
    assert _decode(r.content).size == (200, 600)


def test_image_route_missing_photo_is_404(client, make_image):
    b, cid = _ready_photo(client, make_image)
    svc = client.app.state.services
    batch = svc.store.get(b)
    svc.store.photo_path(b, batch.captures[0]).unlink()
    r = client.get(f"/captures/{cid}/image", headers=H)
    assert r.status_code == 404
    assert error_code(r) == "no_image"


def test_delete_capture_removes_photo_and_preview(client, make_image):
    b, cid = _ready_photo(client, make_image)
    svc = client.app.state.services
    capture = svc.store.get(b).captures[0]
    client.get(f"/captures/{cid}/image", headers=H)
    assert _previews(svc.paths, b) == [f"{cid}-r0.jpg"]

    assert client.delete(f"/captures/{cid}", headers=H).status_code == 204
    assert _previews(svc.paths, b) == []
    assert not svc.store.photo_path(b, capture).exists()


def test_delete_batch_removes_previews(client, make_image):
    b, cid = _ready_photo(client, make_image)
    svc = client.app.state.services
    client.get(f"/captures/{cid}/image", headers=H)
    assert client.delete(f"/batches/{b}", headers=H).status_code == 204
    assert not svc.paths.batch_dir(b).exists()


def test_previews_never_reach_the_notes_repo(client, bare_remote, make_image):
    connect(client, bare_remote)
    client.post("/books", headers=H, json={"title": "Dune", "kind": "fiction"})
    b = new_batch(client, default_book_slug="dune")
    cid = upload(client, b, make_image("p.png")).json()["created"][0]["id"]
    wait_status(client, b, cid, "ready")
    client.get(f"/captures/{cid}/image", headers=H)
    client.patch(f"/captures/{cid}", headers=H, json={"status": "approved"})
    assert client.post(f"/batches/{b}/push", headers=H).status_code == 200

    tree = subprocess.run(
        ["git", "-C", str(bare_remote), "ls-tree", "-r", "--name-only", "main"],
        check=True, capture_output=True, text=True,
    ).stdout.split()
    assert sorted(tree) == ["README.md", "books/dune.md"]
    assert not client.app.state.services.paths.batch_dir(b).exists()  # previews freed with the batch
