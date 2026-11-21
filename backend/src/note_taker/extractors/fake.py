import time
from pathlib import Path

from note_taker.extractors.base import ExtractionError, HealthStatus
from note_taker.models import ExtractionResult


class FakeExtractor:
    """Deterministic stand-in for tests and for running the app without Ollama/Tesseract.

    `healthy` is a plain attribute so a test can flip it to simulate the model coming up.
    """

    name = "fake"

    def __init__(
        self,
        result: ExtractionResult | None = None,
        delay_s: float = 0,
        error: str | None = None,
        healthy: bool = True,
    ):
        self.result = result
        self.delay_s = delay_s
        self.error = error
        self.healthy = healthy
        self.calls: list[tuple[Path, int]] = []

    def health(self) -> HealthStatus:
        return HealthStatus(ok=self.healthy, detail="ok" if self.healthy else "fake extractor is down")

    def extract(self, image_path: Path, rotation: int = 0) -> ExtractionResult:
        self.calls.append((image_path, rotation))
        if self.delay_s:
            time.sleep(self.delay_s)
        if self.error is not None:
            raise ExtractionError(self.error)
        return self.result.model_copy(deep=True) if self.result else ExtractionResult()
