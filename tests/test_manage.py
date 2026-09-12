"""The add/remove command line. No network."""
import pytest

from watch import manage, products


def written(tmp_path, entries):
    p = tmp_path / "products.json"
    products.save(p, entries)
    return p


def test_add_writes_the_file(tmp_path, capsys):
    p = written(tmp_path, [])
    code = manage.main(["--action", "add", "--product",
                        "https://www.amazon.com/dp/B07W1P15GL?th=1",
                        "--label", "Ladle", "--path", str(p)])
    assert code == 0
    entries = products.load(p)
    assert len(entries) == 1
    assert entries[0]["asin"] == "B07W1P15GL"
    assert entries[0]["label"] == "Ladle"
    assert entries[0]["added"].startswith("20")
    assert "B07W1P15GL" in capsys.readouterr().out


def test_add_without_a_label_stores_an_empty_one(tmp_path):
    p = written(tmp_path, [])
    assert manage.main(["--action", "add", "--product", "B07W1P15GL", "--path", str(p)]) == 0
    assert products.load(p)[0]["label"] == ""


def test_add_appends_to_an_existing_list(tmp_path):
    p = written(tmp_path, [{"asin": "B07W1P15GL", "label": "Ladle", "added": ""}])
    assert manage.main(["--action", "add", "--product", "B000000001",
                        "--label", "Kettle", "--path", str(p)]) == 0
    assert [e["asin"] for e in products.load(p)] == ["B07W1P15GL", "B000000001"]


def test_remove_writes_the_file(tmp_path):
    p = written(tmp_path, [{"asin": "B07W1P15GL", "label": "", "added": ""}])
    assert manage.main(["--action", "remove", "--product", "B07W1P15GL", "--path", str(p)]) == 0
    assert products.load(p) == []


def test_remove_accepts_a_url(tmp_path):
    p = written(tmp_path, [{"asin": "B07W1P15GL", "label": "", "added": ""}])
    assert manage.main(["--action", "remove", "--product",
                        "https://www.amazon.com/gp/product/B07W1P15GL", "--path", str(p)]) == 0
    assert products.load(p) == []


def test_a_bad_product_string_fails_and_leaves_the_file_alone(tmp_path, capsys):
    p = written(tmp_path, [{"asin": "B07W1P15GL", "label": "", "added": ""}])
    before = p.read_text(encoding="utf-8")
    assert manage.main(["--action", "add", "--product", "nonsense", "--path", str(p)]) == 1
    assert p.read_text(encoding="utf-8") == before
    assert "nonsense" in capsys.readouterr().err


def test_a_duplicate_fails_and_leaves_the_file_alone(tmp_path, capsys):
    p = written(tmp_path, [{"asin": "B07W1P15GL", "label": "", "added": ""}])
    before = p.read_text(encoding="utf-8")
    assert manage.main(["--action", "add", "--product", "B07W1P15GL", "--path", str(p)]) == 1
    assert p.read_text(encoding="utf-8") == before
    assert "already being watched" in capsys.readouterr().err


def test_removing_an_unwatched_product_fails(tmp_path, capsys):
    p = written(tmp_path, [])
    assert manage.main(["--action", "remove", "--product", "B07W1P15GL", "--path", str(p)]) == 1
    assert "not being watched" in capsys.readouterr().err


def test_an_unknown_action_is_rejected(tmp_path):
    p = written(tmp_path, [])
    with pytest.raises(SystemExit):
        manage.main(["--action", "wipe", "--product", "B07W1P15GL", "--path", str(p)])
