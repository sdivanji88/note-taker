import json
import logging

import pytest

from note_taker.jsonio import quarantine, write_json_atomic
from note_taker.models import ExtractorKind, Settings
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


@pytest.mark.parametrize(
    "content",
    [
        b"{not json",
        b'{"extractor": {"concurrency": "many"}}',  # schema-invalid
        b'["a list"]',
        b"\xff\xfe\x00 not utf-8",
    ],
)
def test_corrupt_settings_load_defaults_and_are_quarantined(data_paths, content, caplog):
    data_paths.root.mkdir(parents=True, exist_ok=True)
    data_paths.settings_file.write_bytes(content)
    store = SettingsStore(data_paths)
    with caplog.at_level(logging.WARNING):
        assert store.load() == Settings()
    backup = data_paths.settings_file.with_name("settings.json.corrupt")
    assert backup.read_bytes() == content
    assert not data_paths.settings_file.exists()
    assert any("settings" in r.getMessage() for r in caplog.records)


def test_load_after_quarantine_returns_defaults_and_save_works(data_paths):
    data_paths.root.mkdir(parents=True, exist_ok=True)
    data_paths.settings_file.write_text("{nope")
    store = SettingsStore(data_paths)
    store.load()
    assert store.load() == Settings()  # file is gone; plain first-run path
    s = Settings()
    s.notes_repo.branch = "dev"
    store.save(s)
    assert SettingsStore(data_paths).load().notes_repo.branch == "dev"


def test_quarantine_replaces_an_earlier_backup(tmp_path):
    f = tmp_path / "x.json"
    f.write_text("first")
    quarantine(f)
    f.write_text("second")
    quarantine(f)
    assert (tmp_path / "x.json.corrupt").read_text() == "second"


def test_quarantine_never_raises_when_file_already_moved(tmp_path):
    quarantine(tmp_path / "missing.json")  # lost a race with another quarantine


def test_valid_settings_are_not_quarantined(data_paths):
    data_paths.root.mkdir(parents=True, exist_ok=True)
    data_paths.settings_file.write_text(json.dumps(Settings().model_dump(mode="json")))
    SettingsStore(data_paths).load()
    assert not data_paths.settings_file.with_name("settings.json.corrupt").exists()
