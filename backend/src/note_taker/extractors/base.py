from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from note_taker.models import ExtractionResult


class ExtractionError(Exception):
    """An extractor understood the request but could not produce a result.

    The message is shown to the user on the failed capture, so keep it readable.
    """


class HealthStatus(BaseModel):
    ok: bool
    detail: str


class Extractor(Protocol):
    name: str

    def health(self) -> HealthStatus: ...

    def extract(self, image_path: Path, rotation: int = 0) -> ExtractionResult:
        """Work on `imaging.load_upright(image_path, rotation)`, never the raw pixels."""
        ...
