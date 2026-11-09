import io
import os
import shutil
from datetime import datetime

import pytesseract
import pytest
from PIL import Image

from note_taker import imaging
from note_taker.batch_store import BatchStore
from note_taker.imaging import captured_at, detect_rotation, downscaled_jpeg_bytes, load_upright
from conftest import dt

needs_tesseract = pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract not installed")


def test_load_upright_applies_orientation(make_image):
    # Orientation 6 means "rotate 90 CW to display": a 600x200 image comes out 200x600.
    p = make_image("o.jpg", fmt="JPEG", exif_orientation=6)
    img = load_upright(p)
    assert img.size == (200, 600)


def test_load_upright_applies_extra_rotation(make_image):
    original = Image.open(make_image("up.png")).convert("RGB")
    sideways = make_image("side.png", pixel_rotation=90)
    img = load_upright(sideways, 270).convert("RGB")
    assert img.size == original.size
    # Lossless quarter turns: the round trip reproduces the pixels exactly.
    assert img.tobytes() == original.tobytes()


def test_load_upright_rotation_is_clockwise(make_image):
    # The highlighter box sits at the top-left of the upright image; after a 90° CW
    # turn it must be at the top-right.
    img = load_upright(make_image("up.png"), 90).convert("RGB")
    w, _ = img.size
    assert img.getpixel((w - 40, 30)) == (255, 235, 59)


def test_captured_at_from_exif(make_image):
    p = make_image("e.jpg", fmt="JPEG", exif_datetime="2026:11:08 21:14:05")
    got = captured_at(p, dt(2000, 1, 1))
    # EXIF has no zone; it is the camera's local wall-clock time.
    expected = datetime(2026, 11, 8, 21, 14, 5).astimezone()
    assert got == expected
    assert got.tzinfo is not None


def test_captured_at_falls_back_to_mtime(make_image):
    p = make_image("m.png")
    when = dt(2026, 10, 1, 12, 30)
    os.utime(p, (when.timestamp(), when.timestamp()))
    got = captured_at(p, dt(2000, 1, 1))
    assert got == when and got.tzinfo is not None


def test_captured_at_ignores_garbage_exif(make_image):
    p = make_image("g.jpg", fmt="JPEG", exif_datetime="not a date")
    when = dt(2026, 10, 1, 12, 30)
    os.utime(p, (when.timestamp(), when.timestamp()))
    assert captured_at(p, dt(2000, 1, 1)) == when


def test_captured_at_missing_file_uses_fallback(tmp_path):
    fallback = dt(2026, 11, 9)
    assert captured_at(tmp_path / "nope.jpg", fallback) == fallback


def test_downscale_caps_long_edge(tmp_path):
    p = tmp_path / "big.png"
    Image.new("RGB", (4000, 1000), "white").save(p)
    out = Image.open(io.BytesIO(downscaled_jpeg_bytes(p)))
    assert out.format == "JPEG"
    assert out.size == (2000, 500)


def test_downscale_keeps_small_images_and_applies_rotation(make_image):
    out = Image.open(io.BytesIO(downscaled_jpeg_bytes(make_image("s.png"), rotation=90)))
    assert out.size == (200, 600)


def test_add_photo_uses_exif_captured_at(data_paths, make_image):
    store = BatchStore(data_paths)
    b = store.create(None)
    p = make_image("e.jpg", fmt="JPEG", exif_datetime="2026:11:08 21:14:05")
    cap = store.add_photo(b.id, "e.jpg", p.read_bytes())
    assert cap.captured_at == datetime(2026, 11, 8, 21, 14, 5).astimezone()
    assert store.get(b.id).captures[0].captured_at == cap.captured_at


@needs_tesseract
def test_detect_rotation_on_sideways_image(make_image):
    text = "The quick brown fox jumps over the lazy dog again and again"
    sideways = make_image("side.png", highlight_text=text, plain_text=text, pixel_rotation=90)
    upright = make_image("up.png", highlight_text=text, plain_text=text)
    assert detect_rotation(sideways) == 270
    assert detect_rotation(upright) == 0


def test_detect_rotation_returns_zero_without_tesseract(make_image, monkeypatch):
    def missing(*a, **k):
        raise pytesseract.TesseractNotFoundError()

    monkeypatch.setattr(imaging.pytesseract, "image_to_osd", missing)
    assert detect_rotation(make_image("x.png", pixel_rotation=90)) == 0


def test_detect_rotation_uses_confident_osd(make_image, monkeypatch):
    monkeypatch.setattr(
        imaging.pytesseract, "image_to_osd", lambda *a, **k: {"rotate": 270, "orientation_conf": 9.5}
    )
    assert detect_rotation(make_image("x.png")) == 270


def test_detect_rotation_ignores_low_confidence(make_image, monkeypatch):
    monkeypatch.setattr(
        imaging.pytesseract, "image_to_osd", lambda *a, **k: {"rotate": 90, "orientation_conf": 1.2}
    )
    assert detect_rotation(make_image("x.png")) == 0


def test_detect_rotation_never_raises_on_unreadable_file(tmp_path):
    p = tmp_path / "broken.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\nnot really")
    assert detect_rotation(p) == 0
