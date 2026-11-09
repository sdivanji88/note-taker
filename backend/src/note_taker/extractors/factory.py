from note_taker.extractors.base import Extractor
from note_taker.extractors.ollama import OllamaVisionExtractor
from note_taker.models import ExtractorKind, ExtractorSettings


def build_extractor(s: ExtractorSettings, kind: ExtractorKind | None = None) -> Extractor:
    """The configured extractor, or `kind` when the user retries with the other one."""
    chosen = kind or s.kind
    if chosen is ExtractorKind.ollama:
        return OllamaVisionExtractor(s.ollama.base_url, s.ollama.model, s.timeout_s)
    if chosen is ExtractorKind.tesseract:
        raise NotImplementedError("Tesseract extractor arrives in Task 9")
    raise ValueError(f"unknown extractor kind: {chosen!r}")
