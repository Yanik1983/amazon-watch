"""Persist watcher state between polls as JSON."""
from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)


def default_state() -> dict:
    return {
        "last_checked": None,   # ISO datetime (UTC) of the last poll attempt
        "last_success": None,   # ISO datetime (UTC) of the last successful fetch + parse
        "fail_count": 0,        # consecutive failed polls
        "last_error": None,     # message of the most recent failure, cleared on success
        "product": None,        # dict of the last parsed Product plus "checked_at"
    }


def load(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return default_state()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError) as e:
        log.warning("state file unreadable (%s); starting fresh", e)
        return default_state()
    base = default_state()
    if isinstance(data, dict):
        base.update(data)
    return base


def save(path: str | Path, state: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
