import json
from datetime import datetime, timezone

from watch import history

NOW = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)


def test_load_missing_returns_empty(tmp_path):
    assert history.load(tmp_path / "nope.json") == []


def test_load_corrupt_returns_empty(tmp_path):
    p = tmp_path / "h.json"
    p.write_text("[oops", encoding="utf-8")
    assert history.load(p) == []


def test_append_and_roundtrip(tmp_path):
    p = tmp_path / "h.json"
    entries = history.load(p)
    history.append_flip(entries, NOW, free=False, delivery_text="ILS 58.91")
    history.append_flip(entries, NOW.replace(hour=11), free=True, delivery_text="FREE")
    history.save(p, entries)
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw == [
        {"at": "2026-09-12T10:00:00+00:00", "free": False, "delivery_text": "ILS 58.91"},
        {"at": "2026-09-12T11:00:00+00:00", "free": True, "delivery_text": "FREE"},
    ]
    assert history.load(p) == raw
