"""Record every change of free-shipping eligibility as a list of flips."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from watch.jsonio import read_json, write_json


def load(path: str | Path) -> list[dict]:
    data = read_json(path, [], "history")
    return data if isinstance(data, list) else []


def save(path: str | Path, entries: list[dict]) -> None:
    write_json(path, entries)


def append_flip(entries: list[dict], when: datetime, free: bool, delivery_text: str) -> None:
    entries.append({"at": when.isoformat(), "free": bool(free), "delivery_text": delivery_text})
