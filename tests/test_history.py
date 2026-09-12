"""History records one flip per product."""
import json
from datetime import datetime, timezone

from watch import config, history

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
    history.append_flip(entries, NOW, "B07W1P15GL", False, "ILS 58.91")
    history.append_flip(entries, NOW.replace(hour=11), "B07W1P15GL", True, "FREE")
    history.save(p, entries)
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw == [
        {"at": "2026-09-12T10:00:00+00:00", "asin": "B07W1P15GL",
         "free": False, "delivery_text": "ILS 58.91"},
        {"at": "2026-09-12T11:00:00+00:00", "asin": "B07W1P15GL",
         "free": True, "delivery_text": "FREE"},
    ]
    assert history.load(p) == raw


def test_version_1_entries_belong_to_the_default_asin(tmp_path):
    p = tmp_path / "h.json"
    p.write_text(json.dumps([{"at": NOW.isoformat(), "free": False, "delivery_text": "ILS 58.91"}]),
                 encoding="utf-8")
    assert history.load(p)[0]["asin"] == config.DEFAULT_ASIN


def test_for_asin_filters():
    entries = []
    history.append_flip(entries, NOW, "B07W1P15GL", True, "FREE")
    history.append_flip(entries, NOW, "B000000001", False, "$5.00")
    assert [e["asin"] for e in history.for_asin(entries, "B000000001")] == ["B000000001"]
    assert history.for_asin(entries, "B0NOSUCH01") == []
