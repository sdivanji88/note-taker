import json
import logging
import os
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)


def write_json_atomic(path: Path, data: dict) -> None:
    """Write via temp file in the same dir + os.replace so readers never see a partial file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def read_json(path: Path) -> dict | None:
    """Return parsed JSON, or None if the file does not exist."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def quarantine(path: Path) -> None:
    """Move an unreadable file to `<name>.corrupt` (replacing an earlier backup).

    Keeps the bytes for manual recovery instead of letting the next write overwrite them.
    Never raises: a concurrent caller may already have moved it, and a failure to move
    must not turn "tolerate a corrupt file" back into a crash.
    """
    path = Path(path)
    backup = path.with_name(path.name + ".corrupt")
    try:
        path.replace(backup)
    except OSError as exc:
        log.warning("could not quarantine %s: %s", path, exc)
        return
    log.warning("unreadable file %s moved to %s", path.name, backup)
