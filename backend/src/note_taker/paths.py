from pathlib import Path

from note_taker.models import Settings


class DataPaths:
    """Single owner of the on-disk layout under the app data dir."""

    def __init__(self, root: Path):
        self.root = Path(root)

    @property
    def settings_file(self) -> Path:
        return self.root / "settings.json"

    @property
    def pending_books_file(self) -> Path:
        return self.root / "pending_books.json"

    @property
    def batches_dir(self) -> Path:
        return self.root / "batches"

    @property
    def default_repo_dir(self) -> Path:
        return self.root / "repo"

    def batch_dir(self, id: str) -> Path:
        return self.batches_dir / id

    def batch_file(self, id: str) -> Path:
        return self.batch_dir(id) / "batch.json"

    def photos_dir(self, id: str) -> Path:
        return self.batch_dir(id) / "photos"


def repo_dir(paths: DataPaths, settings: Settings) -> Path:
    local = settings.notes_repo.local_path
    return Path(local) if local else paths.default_repo_dir
