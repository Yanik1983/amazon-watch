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


def test_save_leaves_no_temp_file_behind(tmp_path):
    p = tmp_path / "state.json"
    state.save(p, state.default_state())
    assert [f.name for f in tmp_path.iterdir()] == ["state.json"]


def test_save_replaces_previous_content_atomically(tmp_path, monkeypatch):
    import os

    p = tmp_path / "state.json"
    s = state.default_state()
    s["fail_count"] = 1
    state.save(p, s)
    seen = {}
    real_replace = os.replace

    def spy(src, dst):
        # the target still holds the old, complete content until the rename lands
        seen["before"] = json.loads(p.read_text(encoding="utf-8"))["fail_count"]
        real_replace(src, dst)

    monkeypatch.setattr("watch.jsonio.os.replace", spy)
    s["fail_count"] = 2
    state.save(p, s)
    assert seen["before"] == 1
    assert state.load(p)["fail_count"] == 2
