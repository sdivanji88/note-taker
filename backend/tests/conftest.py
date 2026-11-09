from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from note_taker.models import Batch, Capture, CaptureStatus, Source
from note_taker.paths import DataPaths


def dt(y, m, d, h=0, mi=0, s=0) -> datetime:
    return datetime(y, m, d, h, mi, s, tzinfo=UTC)


def make_batch(statuses=(), updated_at=None) -> Batch:
    when = dt(2026, 11, 1)
    return Batch(
        id="B1",
        created_at=when,
        updated_at=updated_at or when,
        captures=[
            Capture(id=f"C{i}", source=Source.photo, captured_at=when, status=CaptureStatus(st))
            for i, st in enumerate(statuses)
        ],
    )


@pytest.fixture
def data_paths(tmp_path) -> DataPaths:
    return DataPaths(tmp_path)


@pytest.fixture
def make_image(tmp_path):
    def _make(
        name,
        fmt="PNG",
        highlight_text="mathematical possibility",
        plain_text="other words",
        exif_orientation=None,
        exif_datetime=None,
        pixel_rotation=0,
    ) -> Path:
        img = Image.new("RGB", (600, 200), "white")
        draw = ImageDraw.Draw(img)
        font = ImageFont.load_default(size=28)
        box = draw.textbbox((20, 30), highlight_text, font=font)
        draw.rectangle(box, fill=(255, 235, 59))
        draw.text((20, 30), highlight_text, fill="black", font=font)
        draw.text((20, 120), plain_text, fill="black", font=font)
        if pixel_rotation:
            # PIL rotates counter-clockwise; negate for clockwise.
            img = img.rotate(-pixel_rotation, expand=True, fillcolor="white")
        exif = Image.Exif()
        if exif_orientation is not None:
            exif[0x0112] = exif_orientation
        if exif_datetime is not None:
            exif[0x9003] = exif_datetime
        path = tmp_path / name
        kwargs = {"exif": exif} if len(exif) and fmt.upper() in ("JPEG", "JPG") else {}
        img.save(path, fmt, **kwargs)
        return path

    return _make
