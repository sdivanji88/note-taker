from note_taker.jsonio import write_json_atomic
from note_taker.models import ExtractorKind
from note_taker.settings_store import SettingsStore


def test_settings_defaults_and_roundtrip(data_paths):
    store = SettingsStore(data_paths)
    s = store.load()
    assert s.batches.expiry_days == 30 and s.extractor.timeout_s == 180 and s.notes_repo.branch == "main"
    s.extractor.kind = ExtractorKind.tesseract
    store.save(s)
    assert SettingsStore(data_paths).load().extractor.kind == "tesseract"


def test_write_json_atomic_leaves_no_temp_files(tmp_path):
    write_json_atomic(tmp_path / "a.json", {"x": 1})
    assert [p.name for p in tmp_path.iterdir()] == ["a.json"]
