import io
import logging
from datetime import UTC, datetime
from pathlib import Path

import pytesseract
from PIL import Image, ImageOps

log = logging.getLogger(__name__)

_EXIF_IFD = 0x8769
_DATETIME_ORIGINAL = 36867
# Below this Tesseract's orientation guess is close to noise; leaving the photo as-is
# is cheaper for the user to fix than a confidently wrong turn.
_MIN_OSD_CONFIDENCE = 2.0
_OSD_MAX_EDGE = 1600

# Clockwise quarter turns as lossless transposes (PIL's ROTATE_* are counter-clockwise).
_CLOCKWISE = {
    90: Image.Transpose.ROTATE_270,
    180: Image.Transpose.ROTATE_180,
    270: Image.Transpose.ROTATE_90,
}


def load_upright(path: Path, rotation: int = 0) -> Image.Image:
    """The image as the reader saw the page: EXIF orientation first, then the
    capture's own clockwise `rotation` for photos that are sideways in the pixels."""
    with Image.open(path) as img:
        upright = ImageOps.exif_transpose(img)
    turn = _CLOCKWISE.get(rotation % 360)
    return upright.transpose(turn) if turn is not None else upright


def detect_rotation(path: Path) -> int:
    """Clockwise degrees that make the text upright, or 0 when unsure.

    Best-effort by design: Tesseract may be missing or OSD may find too little text,
    and none of that should stop extraction, so every failure means "leave it".
    """
    try:
        img = load_upright(path).convert("L")
        img.thumbnail((_OSD_MAX_EDGE, _OSD_MAX_EDGE))
        osd = pytesseract.image_to_osd(img, output_type=pytesseract.Output.DICT)
        rotate = int(osd["rotate"]) % 360
        confidence = float(osd["orientation_conf"])
    except Exception as exc:  # noqa: BLE001 - any failure degrades to "no rotation"
        log.info("rotation detection unavailable for %s: %s", path.name, exc)
        return 0
    if confidence < _MIN_OSD_CONFIDENCE or rotate not in (0, 90, 180, 270):
        return 0
    return rotate


def captured_at(path: Path, fallback: datetime) -> datetime:
    """When the page was photographed: EXIF DateTimeOriginal, else file mtime, else fallback."""
    try:
        with Image.open(path) as img:
            exif = img.getexif()
        # Cameras put it in the Exif sub-IFD; some writers put it in IFD0.
        raw = exif.get_ifd(_EXIF_IFD).get(_DATETIME_ORIGINAL) or exif.get(_DATETIME_ORIGINAL)
        if raw:
            # EXIF carries no zone: it is the phone's local wall clock.
            return datetime.strptime(str(raw).strip("\x00 "), "%Y:%m:%d %H:%M:%S").astimezone()
    except (OSError, ValueError, SyntaxError):
        pass
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    except OSError:
        return fallback


def downscaled_jpeg_bytes(path: Path, max_edge: int = 2000, rotation: int = 0) -> bytes:
    """Upright JPEG no larger than `max_edge` on its long side, for vision models."""
    img = load_upright(path, rotation).convert("RGB")
    img.thumbnail((max_edge, max_edge))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return buf.getvalue()
