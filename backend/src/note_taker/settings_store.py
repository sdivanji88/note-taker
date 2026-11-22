import logging
import threading

from note_taker.jsonio import quarantine, read_json, write_json_atomic
from note_taker.models import Settings
from note_taker.paths import DataPaths

log = logging.getLogger(__name__)

# Serialises load's read-validate-quarantine against save, so a save that lands between
# load reading corrupt bytes and quarantining can't have its fresh file moved aside.
# Module-wide like batch_store._LOCK: every instance shares one settings.json.
_LOCK = threading.Lock()


class SettingsStore:
    def __init__(self, paths: DataPaths):
        self._paths = paths

    def load(self) -> Settings:
        """Saved settings, or defaults if none exist or the file is unreadable.

        A corrupt settings.json is quarantined rather than raised: settings load at
        startup, so raising would keep the backend (and the Settings screen that could
        repair it) from ever coming up. OSError is deliberately not caught — an
        unreadable disk is not a corrupt file and quarantining would hide it.
        """
        path = self._paths.settings_file
        with _LOCK:
            try:
                data = read_json(path)
                return Settings.model_validate(data) if data is not None else Settings()
            except ValueError as exc:  # JSON, UnicodeDecode and pydantic validation errors
                log.warning("settings file unreadable, using defaults: %s", exc)
                quarantine(path)
                return Settings()

    def save(self, s: Settings) -> None:
        with _LOCK:
            write_json_atomic(self._paths.settings_file, s.model_dump(mode="json"))
