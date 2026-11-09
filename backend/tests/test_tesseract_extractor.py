import shutil

import numpy as np
import pytesseract
import pytest
from PIL import Image

from note_taker.extractors import tesseract as tess
from note_taker.extractors.base import ExtractionError
from note_taker.extractors.tesseract import (
    TesseractExtractor,
    find_highlight_regions,
    find_page_number,
    group_into_passages,
)

LOW, HIGH = (20, 80, 120), (40, 255, 255)
YELLOW_RGB = (255, 235, 59)


def blank(w=600, h=400):
    return np.full((h, w, 3), 255, np.uint8)


def paint(img, x, y, w, h):
    img[y : y + h, x : x + w] = YELLOW_RGB[::-1]  # BGR


def save(img_bgr, path):
    Image.fromarray(img_bgr[:, :, ::-1]).save(path)
    return path


def extractor():
    return TesseractExtractor(LOW, HIGH, "eng")


def test_find_regions_on_synthetic_image():
    img = blank()
    paint(img, 50, 100, 300, 30)
    regions = find_highlight_regions(img, LOW, HIGH)
    assert len(regions) == 1
    x, y, w, h = regions[0]
    assert x <= 50 + 5 and y <= 100 + 5 and x + w >= 350 - 5 and y + h >= 130 - 5


def test_no_yellow_returns_empty():
    assert find_highlight_regions(blank(), LOW, HIGH) == []


def test_tiny_specks_are_dropped():
    img = blank()
    paint(img, 10, 10, 5, 5)
    assert find_highlight_regions(img, LOW, HIGH) == []


def test_regions_sorted_top_to_bottom():
    img = blank()
    paint(img, 50, 300, 300, 30)
    paint(img, 50, 50, 300, 30)
    ys = [r[1] for r in find_highlight_regions(img, LOW, HIGH)]
    assert ys == sorted(ys) and len(ys) == 2


def test_group_adjacent_lines_into_one_passage():
    boxes = [(10, 100, 300, 30), (10, 135, 300, 30), (10, 300, 300, 30)]
    groups = group_into_passages(boxes, line_gap_px=45)
    assert [len(g) for g in groups] == [2, 1]


def test_group_empty():
    assert group_into_passages([], 45) == []


@pytest.mark.parametrize(
    "text,expected",
    [
        ("163", 163),
        ("  - 42 -  ", 42),
        ("Chapter 3 end", 3),
        ("abc123", None),
        ("page12", None),
        ("12345", None),
        ("", None),
        ("x 7 y 8", 7),
    ],
)
def test_find_page_number(text, expected):
    assert find_page_number(text) == expected


def test_health_false_when_binary_missing(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _: None)
    h = extractor().health()
    assert not h.ok and "brew install tesseract" in h.detail


def test_health_ok_when_binary_present(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/tesseract")
    h = extractor().health()
    assert h.ok and h.detail == "ok"


def test_invalid_hsv_range_is_extraction_error(tmp_path):
    path = save(blank(), tmp_path / "p.png")
    bad = TesseractExtractor((20, 80), HIGH, "eng")
    with pytest.raises(ExtractionError, match="invalid highlight color range"):
        bad.extract(path)


def test_out_of_range_hsv_is_extraction_error(tmp_path):
    path = save(blank(), tmp_path / "p.png")
    bad = TesseractExtractor((20, 80, 120), (40, 300, 255), "eng")
    with pytest.raises(ExtractionError, match="invalid highlight color range"):
        bad.extract(path)


def test_no_highlights_gives_empty_result_without_ocr_on_regions(tmp_path, monkeypatch):
    path = save(blank(), tmp_path / "p.png")
    monkeypatch.setattr(tess, "_ocr", lambda image, psm, lang, timeout: "")
    result = extractor().extract(path)
    assert result.highlights == [] and result.note is None and result.chapter is None


def test_extract_assembles_passages_and_bbox(tmp_path, monkeypatch):
    img = blank()
    paint(img, 50, 100, 300, 30)
    paint(img, 50, 135, 300, 30)  # adjacent line: same passage
    paint(img, 50, 300, 300, 30)  # separate passage
    path = save(img, tmp_path / "p.png")
    texts = iter(["first  line\n", "second\nline", "lonely"])

    def fake(image, psm, lang, timeout):
        assert lang == "eng" and timeout > 0
        if psm == 7:
            return ""
        assert psm == 6
        return next(texts)

    monkeypatch.setattr(tess, "_ocr", fake)
    result = extractor().extract(path)
    assert [h.text for h in result.highlights] == ["first line second line", "lonely"]
    x, y, w, h = result.highlights[0].bbox
    assert y <= 105 and y + h >= 160 and x <= 55 and x + w >= 345
    assert result.highlights[1].bbox[1] >= 290


def test_empty_ocr_text_is_dropped(tmp_path, monkeypatch):
    img = blank()
    paint(img, 50, 100, 300, 30)
    path = save(img, tmp_path / "p.png")
    monkeypatch.setattr(tess, "_ocr", lambda image, psm, lang, timeout: "  \n ")
    assert extractor().extract(path).highlights == []


def _strip_fake(top, bottom):
    # The top strip is the only crop containing the black band drawn by the test.
    def fake(image, psm, lang, timeout):
        if psm == 6:
            return "text"
        return top if np.asarray(image).mean() < 200 else bottom

    return fake


def _page_image(tmp_path):
    img = blank(600, 200)
    paint(img, 50, 80, 300, 30)
    img[0:8, :] = 0
    return save(img, tmp_path / "p.png")


def test_page_number_prefers_bottom_strip(tmp_path, monkeypatch):
    monkeypatch.setattr(tess, "_ocr", _strip_fake("11", "22"))
    assert extractor().extract(_page_image(tmp_path)).page == 22


def test_page_number_falls_back_to_top_strip(tmp_path, monkeypatch):
    monkeypatch.setattr(tess, "_ocr", _strip_fake("11", "abc7"))
    assert extractor().extract(_page_image(tmp_path)).page == 11


def test_page_number_none_when_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(tess, "_ocr", _strip_fake("", "chapter"))
    assert extractor().extract(_page_image(tmp_path)).page is None


def test_bbox_is_in_upright_coordinates_after_rotation(tmp_path, monkeypatch):
    img = blank(600, 200)
    paint(img, 20, 20, 200, 30)  # top-left in the stored pixels
    path = save(img, tmp_path / "p.png")
    monkeypatch.setattr(tess, "_ocr", lambda image, psm, lang, timeout: "word")
    result = extractor().extract(path, rotation=90)
    x, y, w, h = result.highlights[0].bbox
    # 90 degrees clockwise: the upright image is 200x600 and the box moves to the top-right.
    assert x >= 140 and y <= 25 and h >= 150 and x + w <= 200


@pytest.mark.parametrize(
    "exc,expected",
    [
        (pytesseract.TesseractNotFoundError(), "not found"),
        (RuntimeError("Tesseract process timeout"), "timed out"),
        (pytesseract.TesseractError(1, "boom"), "OCR failed"),
    ],
)
def test_ocr_failures_map_to_extraction_error(tmp_path, monkeypatch, exc, expected):
    img = blank()
    paint(img, 50, 100, 300, 30)
    path = save(img, tmp_path / "p.png")

    def boom(image, psm, lang, timeout):
        raise exc

    monkeypatch.setattr(tess, "_ocr", boom)
    with pytest.raises(ExtractionError, match=expected):
        extractor().extract(path)


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract binary not installed")
def test_extract_reads_only_highlighted_text(make_image):
    result = extractor().extract(make_image("p.png"))
    joined = " ".join(h.text for h in result.highlights).lower()
    assert "mathematical" in joined
    assert "other" not in joined
