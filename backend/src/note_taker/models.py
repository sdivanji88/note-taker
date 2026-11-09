from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator
from ulid import ULID


def _new_id() -> str:
    return str(ULID())


class Source(StrEnum):
    photo = "photo"
    kindle = "kindle"


class Kind(StrEnum):
    fiction = "fiction"
    non_fiction = "non-fiction"


class CaptureStatus(StrEnum):
    pending = "pending"
    extracting = "extracting"
    ready = "ready"
    failed = "failed"
    approved = "approved"
    pushed = "pushed"
    discarded = "discarded"


class BatchStatus(StrEnum):
    open = "open"
    pushing = "pushing"
    pushed = "pushed"
    discarded = "discarded"


class ExtractorKind(StrEnum):
    ollama = "ollama"
    tesseract = "tesseract"


class Highlight(BaseModel):
    id: str = Field(default_factory=_new_id)
    text: str
    note: str | None = None


class Capture(BaseModel):
    id: str = Field(default_factory=_new_id)
    source: Source
    image_file: str | None = None
    image_sha256: str | None = None
    # Clockwise degrees applied after EXIF orientation (sideways phone photos).
    rotation: int = 0
    book_slug: str | None = None
    page: int | None = None
    chapter: str | None = None
    captured_at: datetime
    status: CaptureStatus = CaptureStatus.pending
    error: str | None = None
    extractor_used: str | None = None
    highlights: list[Highlight] = Field(default_factory=list)

    @field_validator("rotation")
    @classmethod
    def _rotation_is_quarter_turn(cls, v: int) -> int:
        if v not in (0, 90, 180, 270):
            raise ValueError("rotation must be one of 0, 90, 180, 270")
        return v


class Batch(BaseModel):
    id: str = Field(default_factory=_new_id)
    default_book_slug: str | None = None
    created_at: datetime
    updated_at: datetime
    status: BatchStatus = BatchStatus.open
    warned_at: datetime | None = None
    captures: list[Capture] = Field(default_factory=list)

    def is_finished(self) -> bool:
        # An empty batch is not finished: nothing has been handled yet.
        return bool(self.captures) and all(
            c.status in (CaptureStatus.pushed, CaptureStatus.discarded) for c in self.captures
        )

    def expires_at(self, expiry_days: int) -> datetime:
        # Counted from updated_at so any user edit resets the clock.
        return self.updated_at + timedelta(days=expiry_days)


class Book(BaseModel):
    slug: str
    title: str
    author: str | None = None
    kind: Kind
    pending: bool = False


class PendingBook(BaseModel):
    slug: str
    title: str
    author: str | None = None
    kind: Kind


class ExtractedHighlight(BaseModel):
    text: str
    bbox: tuple[int, int, int, int] | None = None


class ExtractionResult(BaseModel):
    highlights: list[ExtractedHighlight] = Field(default_factory=list)
    note: str | None = None
    page: int | None = None
    chapter: str | None = None
    raw: dict = Field(default_factory=dict)

    @field_validator("page", mode="before")
    @classmethod
    def _coerce_page(cls, v):
        # Models often return roman numerals or "n/a"; treat those as unknown.
        if v is None or isinstance(v, bool):
            return None
        if isinstance(v, int):
            return v
        try:
            return int(str(v).strip())
        except ValueError:
            return None


class NotesRepoSettings(BaseModel):
    remote_url: str = ""
    branch: str = "main"
    local_path: str | None = None
    books_dir: str = "books"


class OllamaSettings(BaseModel):
    base_url: str = "http://localhost:11434"
    model: str = "qwen2.5vl:7b"


class TesseractSettings(BaseModel):
    hsv_low: tuple[int, int, int] = (20, 80, 120)
    hsv_high: tuple[int, int, int] = (40, 255, 255)
    lang: str = "eng"


class ExtractorSettings(BaseModel):
    kind: ExtractorKind = ExtractorKind.ollama
    ollama: OllamaSettings = Field(default_factory=OllamaSettings)
    tesseract: TesseractSettings = Field(default_factory=TesseractSettings)
    concurrency: int = 1
    timeout_s: int = 180


class BatchSettings(BaseModel):
    expiry_days: int = 30
    warn_days_before: int = 7


class Settings(BaseModel):
    notes_repo: NotesRepoSettings = Field(default_factory=NotesRepoSettings)
    extractor: ExtractorSettings = Field(default_factory=ExtractorSettings)
    batches: BatchSettings = Field(default_factory=BatchSettings)
