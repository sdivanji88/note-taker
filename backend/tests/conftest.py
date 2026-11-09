import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from api_helpers import TOKEN
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

from note_taker import imaging
from note_taker.api.app import AppConfig, create_app
from note_taker.extractors.fake import FakeExtractor
from note_taker.models import (
    Batch,
    Capture,
    CaptureStatus,
    ExtractedHighlight,
    ExtractionResult,
    Source,
)
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


@pytest.fixture(autouse=True)
def hermetic_git(monkeypatch):
    # Tests shell out to real git; isolate them from the developer's global
    # config and identity so they neither depend on nor modify it.
    for key, value in {
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }.items():
        monkeypatch.setenv(key, value)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)


@pytest.fixture
def bare_remote(tmp_path) -> Path:
    """A bare 'origin' on branch main holding one seed commit (README.md)."""
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(remote)],
        check=True, capture_output=True, text=True,
    )
    subprocess.run(
        ["git", "init", "-b", "main", str(seed)], check=True, capture_output=True, text=True
    )
    (seed / "README.md").write_text("# notes\n")
    _git(seed, "add", "README.md")
    _git(seed, "commit", "-m", "seed")
    _git(seed, "push", str(remote), "main")
    return remote


# --- API test world (shared by the test_api*.py modules) ----------------------


@pytest.fixture
def no_osd(monkeypatch):
    # Rotation guessing shells out to Tesseract; modules that aren't testing it opt in
    # (pytestmark usefixtures) so it stays inert and fast.
    monkeypatch.setattr(imaging, "detect_rotation", lambda path: 0)


@pytest.fixture
def fake():
    return FakeExtractor(
        result=ExtractionResult(highlights=[ExtractedHighlight(text="mathematical possibility")])
    )


@pytest.fixture
def make_app(tmp_path, fake):
    clients: list[TestClient] = []

    def _make(extractor=None, **cfg) -> TestClient:
        ex = extractor or fake
        config = AppConfig(data_dir=tmp_path / "data", token=TOKEN, **cfg)
        app = create_app(config, extractor_provider=lambda kind: ex)
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        return client

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


@pytest.fixture
def client(make_app) -> TestClient:
    return make_app()


@pytest.fixture
def gif(tmp_path):
    from PIL import Image

    p = tmp_path / "anim.gif"
    Image.new("RGB", (10, 10), "white").save(p, "GIF")
    return p
