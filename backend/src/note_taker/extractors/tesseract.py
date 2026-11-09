import logging
import re
import shutil
import statistics
from pathlib import Path

import cv2
import numpy as np
import pytesseract

from note_taker.extractors.base import ExtractionError, HealthStatus
from note_taker.imaging import load_upright
from note_taker.models import ExtractedHighlight, ExtractionResult

log = logging.getLogger(__name__)

Box = tuple[int, int, int, int]

# A hung Tesseract cannot be killed by the queue and process exit waits for its thread,
# so every call carries its own deadline.
_OCR_TIMEOUT_S = 60
_CLOSE_KERNEL = (25, 5)  # bridges gaps between words so a highlighted line is one blob
_MIN_AREA_FRACTION = 0.001  # smaller blobs are marker specks, not highlighted text
_LINE_GAP_FACTOR = 1.5
_STRIP_FRACTION = 0.08
_PAGE_TOKEN = re.compile(r"(?<!\d)\d{1,4}(?!\d)")
_HSV_MAX = (179, 255, 255)  # OpenCV's hue is 0-179


def _ocr(image: np.ndarray, psm: int, lang: str, timeout: float) -> str:
    """The only place that touches the Tesseract binary; tests replace it."""
    return pytesseract.image_to_string(image, lang=lang, config=f"--psm {psm}", timeout=timeout)


def find_highlight_regions(img_bgr: np.ndarray, hsv_low, hsv_high) -> list[Box]:
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(hsv_low, np.uint8), np.array(hsv_high, np.uint8))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, _CLOSE_KERNEL)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_area = img_bgr.shape[0] * img_bgr.shape[1] * _MIN_AREA_FRACTION
    boxes = [tuple(int(v) for v in cv2.boundingRect(c)) for c in contours]
    return sorted((b for b in boxes if b[2] * b[3] >= min_area), key=lambda b: (b[1], b[0]))


def group_into_passages(boxes: list[Box], line_gap_px: float) -> list[list[Box]]:
    """Top-to-bottom boxes whose vertical gap is under `line_gap_px` share a passage."""
    passages: list[list[Box]] = []
    bottom = 0
    for box in boxes:
        if passages and box[1] - bottom < line_gap_px:
            passages[-1].append(box)
            bottom = max(bottom, box[1] + box[3])
        else:
            passages.append([box])
            bottom = box[1] + box[3]
    return passages


def find_page_number(text: str) -> int | None:
    """First whitespace-delimited token that is a bare 1-4 digit number.

    Digits glued to letters ("abc123") are OCR noise or running-header text, not a page.
    """
    for token in text.split():
        if _PAGE_TOKEN.fullmatch(token):
            return int(token)
    return None


def _validated_range(low, high) -> tuple[tuple[int, ...], tuple[int, ...]]:
    try:
        lo, hi = tuple(int(v) for v in low), tuple(int(v) for v in high)
    except (TypeError, ValueError) as exc:
        raise ExtractionError(f"invalid highlight color range {low!r}..{high!r}") from exc
    ok = len(lo) == len(hi) == 3 and all(
        0 <= a <= b <= m for a, b, m in zip(lo, hi, _HSV_MAX, strict=True)
    )
    if not ok:
        raise ExtractionError(
            f"invalid highlight color range {low!r}..{high!r} (need HSV low <= high, H 0-179, S/V 0-255)"
        )
    return lo, hi


class TesseractExtractor:
    def __init__(self, hsv_low, hsv_high, lang: str = "eng"):
        self.hsv_low = hsv_low
        self.hsv_high = hsv_high
        self.lang = lang
        self.name = "tesseract"

    def health(self) -> HealthStatus:
        if shutil.which("tesseract") is None:
            return HealthStatus(ok=False, detail="tesseract not found (run: brew install tesseract)")
        return HealthStatus(ok=True, detail="ok")

    def extract(self, image_path: Path, rotation: int = 0) -> ExtractionResult:
        low, high = _validated_range(self.hsv_low, self.hsv_high)
        try:
            upright = load_upright(image_path, rotation).convert("RGB")
        except OSError as exc:
            raise ExtractionError("could not read the photo") from exc
        img = cv2.cvtColor(np.asarray(upright), cv2.COLOR_RGB2BGR)

        boxes = find_highlight_regions(img, low, high)
        highlights = []
        if boxes:
            gap = _LINE_GAP_FACTOR * statistics.median(b[3] for b in boxes)
            for passage in group_into_passages(boxes, gap):
                lines = [self._read(img[y : y + h, x : x + w], 6) for x, y, w, h in passage]
                text = " ".join(" ".join(lines).split())
                if text:
                    highlights.append(ExtractedHighlight(text=text, bbox=_union(passage)))
        # Skip the margin OCR when there is nothing to attach a page to.
        page = self._page_number(img) if highlights else None
        return ExtractionResult(highlights=highlights, page=page)

    def _page_number(self, img: np.ndarray) -> int | None:
        strip = max(1, int(img.shape[0] * _STRIP_FRACTION))
        # Page numbers usually sit at the foot of the page; headers are the fallback.
        for crop in (img[-strip:], img[:strip]):
            page = find_page_number(self._read(crop, 7))
            if page is not None:
                return page
        return None

    def _read(self, crop: np.ndarray, psm: int) -> str:
        # Tesseract is the one boundary here; its failures must read well on the failed capture.
        try:
            return _ocr(crop, psm, self.lang, _OCR_TIMEOUT_S)
        except pytesseract.TesseractNotFoundError as exc:
            raise ExtractionError("tesseract not found (run: brew install tesseract)") from exc
        except pytesseract.TesseractError as exc:
            log.warning("tesseract failed: %s", exc)
            raise ExtractionError("OCR failed") from exc
        except RuntimeError as exc:
            # pytesseract reports its own timeout as a bare RuntimeError.
            raise ExtractionError(f"OCR timed out after {_OCR_TIMEOUT_S}s") from exc


def _union(boxes: list[Box]) -> Box:
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[0] + b[2] for b in boxes)
    y1 = max(b[1] + b[3] for b in boxes)
    return (x0, y0, x1 - x0, y1 - y0)
