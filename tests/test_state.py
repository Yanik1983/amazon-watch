import json

from watch import state


def test_load_missing_returns_default(tmp_path):
    s = state.load(tmp_path / "nope.json")
    assert s == state.default_state()
    assert s["fail_count"] == 0
    assert s["product"] is None
    assert s["last_checked"] is None
    assert s["last_error"] is None


def test_save_then_load_roundtrip(tmp_path):
    p = tmp_path / "state.json"
    s = state.default_state()
    s["fail_count"] = 2
    s["product"] = {"free": False, "delivery_text": "ILS 58.91", "title": "Ladle", "merchant": ""}
    state.save(p, s)
    assert json.loads(p.read_text(encoding="utf-8"))["fail_count"] == 2
    assert state.load(p) == s


def test_load_corrupt_returns_default(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{not json", encoding="utf-8")
    assert state.load(p) == state.default_state()


def test_load_fills_missing_keys(tmp_path):
    p = tmp_path / "state.json"
    p.write_text('{"fail_count": 1}', encoding="utf-8")
    s = state.load(p)
    assert s["fail_count"] == 1
    assert s["product"] is None
