"""Product list: parsing, mutation, labels and ntfy slugs. No network."""
from datetime import datetime, timezone

import pytest

from watch import config, products

WHEN = datetime(2026, 9, 12, 18, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("text", [
    "B07W1P15GL",
    "b07w1p15gl",
    "https://www.amazon.com/dp/B07W1P15GL",
    "https://www.amazon.com/dp/B07W1P15GL?th=1&ref=foo",
    "https://www.amazon.com/gp/product/B07W1P15GL",
    "https://www.amazon.com/DI-ORO-Silicone-Ladle/dp/B07W1P15GL/ref=sr_1_3",
    "  https://amzn.to/x /dp/B07W1P15GL  ",
])
def test_extract_asin_accepts(text):
    assert products.extract_asin(text) == "B07W1P15GL"


@pytest.mark.parametrize("text", ["", "not an asin", "B07W1P15G", "https://www.amazon.com/dp/"])
def test_extract_asin_rejects(text):
    with pytest.raises(products.ProductError):
        products.extract_asin(text)


def test_add_appends_without_mutating():
    entries = []
    out = products.add(entries, "B07W1P15GL", "Ladle", WHEN)
    assert entries == []
    assert out == [{"asin": "B07W1P15GL", "label": "Ladle", "added": WHEN.isoformat()}]


def test_add_accepts_a_url():
    out = products.add([], "https://www.amazon.com/dp/B07W1P15GL?th=1", "", WHEN)
    assert out[0]["asin"] == "B07W1P15GL"


def test_add_rejects_duplicate():
    entries = products.add([], "B07W1P15GL", "", WHEN)
    with pytest.raises(products.ProductError):
        products.add(entries, "B07W1P15GL", "again", WHEN)


def test_remove_drops_without_mutating():
    entries = products.add(products.add([], "B07W1P15GL", "", WHEN), "B000000001", "", WHEN)
    out = products.remove(entries, "B07W1P15GL")
    assert [e["asin"] for e in entries] == ["B07W1P15GL", "B000000001"]
    assert [e["asin"] for e in out] == ["B000000001"]


def test_remove_rejects_unknown():
    with pytest.raises(products.ProductError):
        products.remove([], "B07W1P15GL")


def test_load_bootstraps_when_missing(tmp_path):
    entries = products.load(tmp_path / "products.json")
    assert [e["asin"] for e in entries] == [config.DEFAULT_ASIN]


def test_load_bootstraps_when_unreadable(tmp_path):
    p = tmp_path / "products.json"
    p.write_text("{ not json", encoding="utf-8")
    assert [e["asin"] for e in products.load(p)] == [config.DEFAULT_ASIN]


def test_load_returns_empty_list_when_file_says_so(tmp_path):
    p = tmp_path / "products.json"
    p.write_text('{"products": []}', encoding="utf-8")
    assert products.load(p) == []


def test_save_load_round_trip(tmp_path):
    p = tmp_path / "products.json"
    entries = products.add([], "B07W1P15GL", "Ladle", WHEN)
    products.save(p, entries)
    assert products.load(p) == entries


def test_load_skips_entries_without_a_valid_asin(tmp_path):
    p = tmp_path / "products.json"
    p.write_text('{"products": [{"asin": "nope"}, "junk", {"asin": "B07W1P15GL"}]}',
                 encoding="utf-8")
    assert [e["asin"] for e in products.load(p)] == ["B07W1P15GL"]


def test_display_label_prefers_the_label():
    entry = {"asin": "B07W1P15GL", "label": "Ladle"}
    assert products.display_label(entry, "Some Long Page Title") == "Ladle"


def test_display_label_falls_back_to_a_truncated_title():
    entry = {"asin": "B07W1P15GL", "label": ""}
    title = "x" * (products.DEFAULT_LABEL_CHARS + 20)
    out = products.display_label(entry, title)
    assert len(out) == products.DEFAULT_LABEL_CHARS + 1
    assert out.endswith("…")


def test_display_label_keeps_a_short_title_whole():
    assert products.display_label({"asin": "B07W1P15GL", "label": ""}, "Ladle") == "Ladle"


def test_display_label_falls_back_to_the_asin():
    assert products.display_label({"asin": "B07W1P15GL", "label": ""}, "") == "B07W1P15GL"


def test_slug_folds_punctuation_and_case():
    assert products.slug("DI ORO Silicone Ladle - Soup!", "B07W1P15GL") == "di-oro-silicone-ladle-soup"


def test_slug_folds_accents_to_ascii():
    out = products.slug("Café Crème", "B07W1P15GL")
    assert out == "cafe-creme"
    assert out.isascii()


def test_slug_truncates():
    assert len(products.slug("a" * 100, "B07W1P15GL")) == products.SLUG_CHARS


def test_slug_falls_back_to_the_asin():
    assert products.slug("קומקום", "B07W1P15GL") == "b07w1p15gl"
