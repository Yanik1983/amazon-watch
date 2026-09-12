"""Record every change of free-shipping eligibility as a list of flips."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)


def load(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError) as e:
        log.warning("history file unreadable (%s); starting fresh", e)
        return []
    return data if isinstance(data, list) else []


def save(path: str | Path, entries: list[dict]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")


def append_flip(entries: list[dict], when: datetime, free: bool, delivery_text: str) -> None:
    entries.append({"at": when.isoformat(), "free": bool(free), "delivery_text": delivery_text})
