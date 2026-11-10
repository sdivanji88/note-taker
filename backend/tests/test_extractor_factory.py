import pytest

from note_taker.extractors.base import ExtractionError
from note_taker.extractors.factory import build_extractor
from note_taker.extractors.fake import FakeExtractor
from note_taker.extractors.ollama import OllamaVisionExtractor
from note_taker.extractors.tesseract import TesseractExtractor
from note_taker.models import ExtractionResult, ExtractorKind, ExtractorSettings


def test_fake_extractor_behaviour(tmp_path):
    f = FakeExtractor(error="nope", healthy=False)
    assert f.name == "fake"
    assert f.health().ok is False
    with pytest.raises(ExtractionError, match="nope"):
        f.extract(tmp_path / "x.png", 90)
    assert f.calls == [(tmp_path / "x.png", 90)]
    assert FakeExtractor().extract(tmp_path / "y.png") == ExtractionResult()


def test_build_extractor_returns_ollama_extractor_from_settings():
    s = ExtractorSettings()
    s.ollama.base_url = "http://example:1/"
    s.ollama.model = "mm"
    ex = build_extractor(s, ExtractorKind.ollama)
    assert isinstance(ex, OllamaVisionExtractor)
    assert ex.name == "ollama:mm"


def test_build_extractor_tesseract_branch():
    s = ExtractorSettings()
    ex = build_extractor(s, ExtractorKind.tesseract)
    assert isinstance(ex, TesseractExtractor)
    assert (ex.hsv_low, ex.hsv_high, ex.lang) == (s.tesseract.hsv_low, s.tesseract.hsv_high, s.tesseract.lang)
