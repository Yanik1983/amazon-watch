"""Persist watcher state between polls as JSON."""
from __future__ import annotations

from pathlib import Path

from watch.jsonio import read_json, write_json


def default_state() -> dict:
    return {
        "last_checked": None,   # ISO datetime (UTC) of the last poll attempt
        "last_success": None,   # ISO datetime (UTC) of the last successful fetch + parse
        "fail_count": 0,        # consecutive failed polls
        "last_error": None,     # message of the most recent failure, cleared on success
        "product": None,        # dict of the last parsed Product plus "checked_at"
    }


def load(path: str | Path) -> dict:
    data = read_json(path, None, "state")
    base = default_state()
    if isinstance(data, dict):
        base.update(data)
    return base


def save(path: str | Path, state: dict) -> None:
    write_json(path, state, sort_keys=True)
