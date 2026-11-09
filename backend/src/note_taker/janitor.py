import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from note_taker.batch_store import BatchStore
from note_taker.models import Batch, Settings

log = logging.getLogger(__name__)

# Gives the user at least a day between seeing the warning and losing the batch.
_DELETE_GRACE = timedelta(hours=24)


@dataclass
class JanitorReport:
    warned: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)


def expiring_soon(batch: Batch, settings: Settings, now: datetime) -> bool:
    b = settings.batches
    return now >= batch.expires_at(b.expiry_days) - timedelta(days=b.warn_days_before)


def _action(batch: Batch, settings: Settings, now: datetime) -> str | None:
    """"warn", "delete" or None. Pure so it can be re-evaluated on a freshly read batch."""
    if batch.is_finished():
        return None
    if batch.warned_at is None:
        # Never delete without a prior warning, even if long past expiry.
        return "warn" if expiring_soon(batch, settings, now) else None
    expired = now >= batch.expires_at(settings.batches.expiry_days)
    if expired and now - batch.warned_at >= _DELETE_GRACE:
        return "delete"
    return None


class Janitor:
    def __init__(
        self, store: BatchStore, settings: Callable[[], Settings], now: Callable[[], datetime]
    ):
        self._store = store
        self._settings = settings
        self._now = now

    def run(self) -> JanitorReport:
        # Never raises: it runs on a background timer, and one bad batch must not stop
        # expiry for the rest.
        report = JanitorReport()
        try:
            settings, now = self._settings(), self._now()
            batches = self._store.list_readable()
        except Exception:
            log.exception("janitor could not list batches")
            return report
        for batch in batches:
            try:
                action = _action(batch, settings, now)
                if action == "warn" and self._warn(batch.id, settings, now):
                    report.warned.append(batch.id)
                elif action == "delete" and self._delete(batch.id, settings, now):
                    report.deleted.append(batch.id)
            except Exception:
                log.exception("janitor failed on batch %s", batch.id)
        return report

    def _warn(self, batch_id: str, settings: Settings, now: datetime) -> bool:
        warned = False

        def change(fresh: Batch) -> None:
            nonlocal warned
            # Re-check: the user may have finished or edited the batch since listing.
            if _action(fresh, settings, now) == "warn":
                fresh.warned_at = now
                warned = True

        # touch=False: the warning must not push expiry out.
        self._store.modify(batch_id, change, touch=False)
        if warned:
            log.info("batch %s warned of expiry", batch_id)
        return warned

    def _delete(self, batch_id: str, settings: Settings, now: datetime) -> bool:
        deleted = self._store.delete_if(batch_id, lambda b: _action(b, settings, now) == "delete")
        if deleted:
            log.info("batch %s expired and deleted", batch_id)
        return deleted
