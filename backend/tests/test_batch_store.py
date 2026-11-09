import pytest

from note_taker.batch_store import BatchNotFound, BatchStore, DuplicatePhoto, UnsupportedImage
from note_taker.models import CaptureStatus, Highlight, Source
from conftest import dt


def test_create_get_list_roundtrip(data_paths):
    ticks = iter([dt(2026, 11, 1), dt(2026, 11, 2)])
    store = BatchStore(data_paths, now=lambda: next(ticks))
    a = store.create("book-a")
    b = store.create(None)

    assert store.get(a.id) == a
    assert a.default_book_slug == "book-a"
    assert a.created_at == a.updated_at == dt(2026, 11, 1)
    assert [x.id for x in store.list()] == [a.id, b.id]
    with pytest.raises(BatchNotFound):
        store.get("nope")


def test_add_photo_rejects_gif_and_dedupes_by_sha(data_paths, make_image):
    store = BatchStore(data_paths)
    batch = store.create(None)
    gif = make_image("a.gif", fmt="GIF").read_bytes()
    with pytest.raises(UnsupportedImage):
        store.add_photo(batch.id, "a.png", gif)  # extension lies; magic bytes decide

    png = make_image("a.png").read_bytes()
    store.add_photo(batch.id, "a.png", png)
    with pytest.raises(DuplicatePhoto):
        store.add_photo(batch.id, "again.png", png)


def test_add_photo_writes_file_and_pending_capture(data_paths, make_image):
    store = BatchStore(data_paths, now=lambda: dt(2026, 11, 3))
    batch = store.create(None)
    png = make_image("a.png").read_bytes()
    jpg = make_image("b.jpg", fmt="JPEG").read_bytes()

    c1 = store.add_photo(batch.id, "a.png", png)
    c2 = store.add_photo(batch.id, "b.jpg", jpg)

    assert c1.status == CaptureStatus.pending and c1.source == Source.photo
    assert c1.image_file == f"{c1.id}.png" and c2.image_file == f"{c2.id}.jpg"
    assert store.photo_path(batch.id, c1) == data_paths.photos_dir(batch.id) / c1.image_file
    assert store.photo_path(batch.id, c1).read_bytes() == png
    assert c1.captured_at.tzinfo is not None
    assert [c.id for c in store.get(batch.id).captures] == [c1.id, c2.id]
    assert store.find_capture(c2.id)[1].id == c2.id
    assert store.find_capture(c2.id)[0].id == batch.id


def test_save_touch_false_keeps_updated_at(data_paths):
    ticks = iter([dt(2026, 11, 1), dt(2026, 11, 5), dt(2026, 11, 6)])
    store = BatchStore(data_paths, now=lambda: next(ticks))
    batch = store.create(None)

    store.save(batch, touch=False)
    assert store.get(batch.id).updated_at == dt(2026, 11, 1)
    store.save(batch)
    assert store.get(batch.id).updated_at == dt(2026, 11, 5)


def test_delete_removes_folder(data_paths, make_image):
    store = BatchStore(data_paths)
    batch = store.create(None)
    store.add_photo(batch.id, "a.png", make_image("a.png").read_bytes())

    store.delete(batch.id)

    assert not data_paths.batch_dir(batch.id).exists()
    assert store.list() == []


def test_remove_capture_deletes_photo(data_paths, make_image):
    store = BatchStore(data_paths)
    batch = store.create(None)
    cap = store.add_photo(batch.id, "a.png", make_image("a.png").read_bytes())
    path = store.photo_path(batch.id, cap)
    assert path.exists()

    store.remove_capture(batch.id, cap.id)

    assert not path.exists()
    assert store.get(batch.id).captures == []


def test_add_kindle_is_ready_and_update_capture_persists(data_paths):
    store = BatchStore(data_paths)
    batch = store.create(None)
    cap = store.add_kindle(batch.id, [Highlight(text="hi")], "book-a", 12, "Ch 1", None)

    assert cap.status == CaptureStatus.ready and cap.source == Source.kindle
    assert cap.image_file is None and cap.captured_at.tzinfo is not None
    cap.page = 13
    assert store.update_capture(batch.id, cap).captures[0].page == 13
    assert store.get(batch.id).captures[0].page == 13
