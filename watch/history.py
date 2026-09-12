"""Record every change of free-shipping eligibility as a flat list of flips."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from watch import config
from watch.jsonio import read_json, write_json


def load(path: str | Path) -> list[dict]:
    """Every recorded flip.

    Entries written before products had ASINs belong to the default product,
    which is the only one that version of the watcher could have polled.
    """
    data = read_json(path, [], "history")
    if not isinstance(data, list):
        return []
    return [
        {**e, "asin": e.get("asin") or config.DEFAULT_ASIN}
        for e in data if isinstance(e, dict)
    ]


def save(path: str | Path, entries: list[dict]) -> None:
    write_json(path, entries)


def append_flip(entries: list[dict], when: datetime, asin: str,
                free: bool, delivery_text: str) -> None:
    entries.append({
        "at": when.isoformat(),
        "asin": asin,
        "free": bool(free),
        "delivery_text": delivery_text,
    })


def for_asin(entries: list[dict], asin: str) -> list[dict]:
    return [e for e in entries if e.get("asin") == asin]
