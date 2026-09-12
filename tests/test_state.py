"""State persistence, including migration from the single-product format."""
import json

from watch import config, state


def test_load_missing_returns_default(tmp_path):
    s = state.load(tmp_path / "nope.json")
    assert s == {"version": 2, "last_checked": None, "products": {}, "command_nonces": []}


def test_load_corrupt_returns_default(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{not json", encoding="utf-8")
    assert state.load(p) == state.default_state()


def test_save_then_load_roundtrip(tmp_path):
    p = tmp_path / "state.json"
    s = state.default_state()
    s["last_checked"] = "2026-09-12T10:00:00+00:00"
    e = state.entry(s, "B07W1P15GL")
    e["free"] = False
    e["delivery_text"] = "ILS 58.91"
    e["title"] = "Ladle"
    state.save(p, s)
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw["products"]["B07W1P15GL"]["delivery_text"] == "ILS 58.91"
    assert state.load(p) == s


def test_version_1_file_migrates_under_the_default_asin(tmp_path):
    p = tmp_path / "state.json"
    p.write_text(json.dumps({
        "last_checked": "2026-09-12T17:50:06+00:00",
        "last_success": "2026-09-12T17:50:06+00:00",
        "fail_count": 2,
        "last_error": "boom",
        "product": {
            "checked_at": "2026-09-12T17:50:06+00:00",
            "delivery_text": "$19.28",
            "free": False,
            "merchant": "",
            "title": "DI ORO Silicone Ladle",
        },
    }), encoding="utf-8")
    st = state.load(p)
    assert st["version"] == 2
    assert st["last_checked"] == "2026-09-12T17:50:06+00:00"
    assert "product" not in st
    e = st["products"][config.DEFAULT_ASIN]
    assert e["free"] is False
    assert e["title"] == "DI ORO Silicone Ladle"
    assert e["delivery_text"] == "$19.28"
    assert e["fail_count"] == 2
    assert e["last_error"] == "boom"
    assert e["last_success"] == "2026-09-12T17:50:06+00:00"
    assert e["checked_at"] == "2026-09-12T17:50:06+00:00"


def test_version_1_file_without_a_product_migrates_to_empty(tmp_path):
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"last_checked": "2026-09-12T17:50:06+00:00", "product": None}),
                 encoding="utf-8")
    st = state.load(p)
    assert st["products"] == {}
    assert st["last_checked"] == "2026-09-12T17:50:06+00:00"


def test_a_partial_entry_is_filled_with_defaults(tmp_path):
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"version": 2, "products": {"B07W1P15GL": {"free": True}}}),
                 encoding="utf-8")
    assert state.load(p)["products"]["B07W1P15GL"] == {**state.default_entry(), "free": True}


def test_entry_inserts_a_default_and_returns_the_live_dict():
    st = state.default_state()
    e = state.entry(st, "B07W1P15GL")
    assert e == state.default_entry()
    e["free"] = True
    assert st["products"]["B07W1P15GL"]["free"] is True


def test_entry_returns_the_existing_dict():
    st = state.default_state()
    state.entry(st, "B07W1P15GL")["title"] = "Ladle"
    assert state.entry(st, "B07W1P15GL")["title"] == "Ladle"


def test_command_nonces_round_trip(tmp_path):
    p = tmp_path / "state.json"
    s = state.default_state()
    s["command_nonces"] = ["abc", "def"]
    state.save(p, s)
    assert state.load(p)["command_nonces"] == ["abc", "def"]


def test_a_state_file_without_nonces_loads_an_empty_list(tmp_path):
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"version": 2, "products": {}}), encoding="utf-8")
    assert state.load(p)["command_nonces"] == []


def test_prune_drops_unwatched_products():
    st = state.default_state()
    state.entry(st, "B07W1P15GL")
    state.entry(st, "B000000001")
    state.prune(st, ["B000000001"])
    assert list(st["products"]) == ["B000000001"]


def test_save_leaves_no_temp_file_behind(tmp_path):
    p = tmp_path / "state.json"
    state.save(p, state.default_state())
    assert [f.name for f in tmp_path.iterdir()] == ["state.json"]


def test_save_replaces_previous_content_atomically(tmp_path, monkeypatch):
    import os

    p = tmp_path / "state.json"
    s = state.default_state()
    s["last_checked"] = "first"
    state.save(p, s)
    seen = {}
    real_replace = os.replace

    def spy(src, dst):
        # the target still holds the old, complete content until the rename lands
        seen["before"] = json.loads(p.read_text(encoding="utf-8"))["last_checked"]
        real_replace(src, dst)

    monkeypatch.setattr("watch.jsonio.os.replace", spy)
    s["last_checked"] = "second"
    state.save(p, s)
    assert seen["before"] == "first"
    assert state.load(p)["last_checked"] == "second"
