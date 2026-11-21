from note_taker.jsonio import read_json, write_json_atomic
from note_taker.models import Settings
from note_taker.paths import DataPaths


class SettingsStore:
    def __init__(self, paths: DataPaths):
        self._paths = paths

    def load(self) -> Settings:
        data = read_json(self._paths.settings_file)
        return Settings.model_validate(data) if data is not None else Settings()

    def save(self, s: Settings) -> None:
        write_json_atomic(self._paths.settings_file, s.model_dump(mode="json"))
