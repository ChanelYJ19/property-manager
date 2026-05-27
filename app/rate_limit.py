"""Track which reminders have already been sent to avoid duplicates on restart."""
import json
import logging
import os
from datetime import date, timedelta

log = logging.getLogger(__name__)

_STATE_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "sent_reminders.json"))
_PRUNE_AFTER_DAYS = 60


def _load() -> set:
    if os.path.exists(_STATE_FILE):
        with open(_STATE_FILE) as f:
            return set(json.load(f).get("sent", []))
    return set()


def _save(sent: set) -> None:
    with open(_STATE_FILE, "w") as f:
        json.dump({"sent": sorted(sent)}, f, indent=2)


def _key(sheet_row: int, due_date: str, interval: int) -> str:
    # e.g. "42:2026-06-01:7" or "42:2026-06-01:-3" for overdue
    return f"{sheet_row}:{due_date}:{interval}"


def already_sent(sheet_row: int, due_date: str, interval: int) -> bool:
    return _key(sheet_row, due_date, interval) in _load()


def mark_sent(sheet_row: int, due_date: str, interval: int) -> None:
    sent = _load()
    sent.add(_key(sheet_row, due_date, interval))
    cutoff = (date.today() - timedelta(days=_PRUNE_AFTER_DAYS)).strftime("%Y-%m-%d")
    sent = {k for k in sent if k.split(":")[1] >= cutoff}
    _save(sent)
    log.debug("Marked sent: %s", _key(sheet_row, due_date, interval))
