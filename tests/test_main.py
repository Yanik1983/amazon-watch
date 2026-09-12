"""Poll cycles with fake fetch and fake notifier. No network."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from watch import config, products
from watch.client import FetchError
from watch.main import run
from watch.state import load as load_state

FIX = Path(__file__).parent / "fixtures"
NOT_FREE = (FIX / "not_free.html").read_text(encoding="utf-8")
FREE = (FIX / "free.html").read_text(encoding="utf-8")
NOW = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)

DEF = config.DEFAULT_ASIN          # the Ladle
OTHER = "B000000001"               # a second product used by the multi-product cases


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def __call__(self, title, body, click=None, priority="high", tags=""):
        self.sent.append({"title": title, "body": body, "click": click,
                          "priority": priority, "tags": tags})
        return True


def fetch_returning(html):
    return lambda asin: html


def fetch_failing(asin):
    raise FetchError("first GET: captcha page returned")


def fetch_per_asin(mapping):
    """A fetch serving different HTML per ASIN; a mapped exception is raised instead."""
    def fetch(asin):
        value = mapping[asin]
        if isinstance(value, Exception):
            raise value
        return value
    return fetch


def paths(tmp_path, entries=None):
    """Test paths. products.json is written unless `entries` is None."""
    p = dict(
        products_path=tmp_path / "products.json",
        state_path=tmp_path / "state.json",
        history_path=tmp_path / "history.json",
        page_path=tmp_path / "docs" / "index.html",
    )
    if entries is not None:
        products.save(p["products_path"], entries)
    return p


def entry(asin, label=""):
    return {"asin": asin, "label": label, "added": ""}


def read_history(tmp_path):
    return json.loads((tmp_path / "history.json").read_text(encoding="utf-8"))


# --- one product: the behaviour the watcher shipped with -------------------


def test_first_poll_records_without_push(tmp_path):
    n = FakeNotifier()
    st = run(fetch=fetch_returning(NOT_FREE), notifier=n, now=NOW, **paths(tmp_path))
    assert n.sent == []
    e = st["products"][DEF]
    assert e["free"] is False
    assert e["checked_at"] == NOW.isoformat()
    assert e["last_success"] == NOW.isoformat()
    assert e["fail_count"] == 0
    assert st["last_checked"] == NOW.isoformat()
    assert (tmp_path / "docs" / "index.html").exists()
    assert load_state(tmp_path / "state.json") == st
    hist = read_history(tmp_path)
    assert len(hist) == 1 and hist[0]["free"] is False and hist[0]["asin"] == DEF


def test_missing_products_file_watches_the_default_product(tmp_path):
    n = FakeNotifier()
    st = run(fetch=fetch_returning(NOT_FREE), notifier=n, now=NOW, **paths(tmp_path))
    assert list(st["products"]) == [DEF]
    assert not (tmp_path / "products.json").exists()  # the poll never writes it


def test_paid_to_free_pushes_once(tmp_path):
    n = FakeNotifier()
    p = paths(tmp_path)
    run(fetch=fetch_returning(NOT_FREE), notifier=n, now=NOW, **p)
    run(fetch=fetch_returning(FREE), notifier=n, now=NOW + timedelta(hours=1), **p)
    assert len(n.sent) == 1
    msg = n.sent[0]
    assert msg["title"].startswith("FREE: ")
    assert msg["click"] == config.product_url(DEF)
    assert msg["priority"] == "high"
    assert "FREE" in msg["body"]
    # stays free: no second push
    run(fetch=fetch_returning(FREE), notifier=n, now=NOW + timedelta(hours=2), **p)
    assert len(n.sent) == 1


def test_free_to_paid_records_history_without_push(tmp_path):
    n = FakeNotifier()
    p = paths(tmp_path)
    run(fetch=fetch_returning(FREE), notifier=n, now=NOW, **p)
    assert len(n.sent) == 1  # already free on the first observation: announced once
    run(fetch=fetch_returning(NOT_FREE), notifier=n, now=NOW + timedelta(hours=1), **p)
    assert len(n.sent) == 1  # falling back to paid adds no push
    assert [e["free"] for e in read_history(tmp_path)] == [True, False]


def test_first_poll_pushes_when_already_free(tmp_path):
    n = FakeNotifier()
    st = run(fetch=fetch_returning(FREE), notifier=n, now=NOW, **paths(tmp_path))
    assert len(n.sent) == 1
    assert n.sent[0]["click"] == config.product_url(DEF)
    assert st["products"][DEF]["free"] is True


def test_lost_state_file_re_announces_free(tmp_path):
    n = FakeNotifier()
    p = paths(tmp_path)
    run(fetch=fetch_returning(FREE), notifier=n, now=NOW, **p)
    Path(p["state_path"]).unlink()
    run(fetch=fetch_returning(FREE), notifier=n, now=NOW + timedelta(hours=1), **p)
    assert len(n.sent) == 2


def test_unchanged_state_adds_no_history(tmp_path):
    n = FakeNotifier()
    p = paths(tmp_path)
    run(fetch=fetch_returning(NOT_FREE), notifier=n, now=NOW, **p)
    run(fetch=fetch_returning(NOT_FREE), notifier=n, now=NOW + timedelta(hours=1), **p)
    assert len(read_history(tmp_path)) == 1


def test_failures_alert_once_at_threshold_and_reset(tmp_path):
    n = FakeNotifier()
    p = paths(tmp_path)
    for i in range(1, 5):
        st = run(fetch=fetch_failing, notifier=n, now=NOW, **p)
        assert st["products"][DEF]["fail_count"] == i
        assert "captcha" in st["products"][DEF]["last_error"]
    assert len(n.sent) == 1
    assert n.sent[0]["title"] == "Amazon watcher failing"
    assert n.sent[0]["priority"] == "default"
    assert n.sent[0]["tags"] == "warning"
    st = run(fetch=fetch_returning(NOT_FREE), notifier=n, now=NOW, **p)
    assert st["products"][DEF]["fail_count"] == 0
    assert st["products"][DEF]["last_error"] is None


def test_failures_rewarn_every_24_polls(tmp_path):
    n = FakeNotifier()
    p = paths(tmp_path)
    for _ in range(27):
        run(fetch=fetch_failing, notifier=n, now=NOW, **p)
    assert len(n.sent) == 2
    assert all(msg["title"] == "Amazon watcher failing" for msg in n.sent)


def test_failure_keeps_previous_product(tmp_path):
    n = FakeNotifier()
    p = paths(tmp_path)
    run(fetch=fetch_returning(FREE), notifier=n, now=NOW, **p)
    st = run(fetch=fetch_failing, notifier=n, now=NOW + timedelta(hours=1), **p)
    e = st["products"][DEF]
    assert e["free"] is True
    assert st["last_checked"] == (NOW + timedelta(hours=1)).isoformat()
    assert e["last_success"] == NOW.isoformat()
    page = (tmp_path / "docs" / "index.html").read_text(encoding="utf-8")
    assert "1 consecutive failed polls" in page


def test_parse_error_counts_as_failure(tmp_path):
    n = FakeNotifier()
    st = run(fetch=fetch_returning("<html>no delivery block</html>"), notifier=n,
             now=NOW, **paths(tmp_path))
    assert st["products"][DEF]["fail_count"] == 1
    assert "delivery block" in st["products"][DEF]["last_error"]


# --- several products ------------------------------------------------------


def test_each_product_flips_independently(tmp_path):
    n = FakeNotifier()
    p = paths(tmp_path, [entry(DEF, "Ladle"), entry(OTHER, "Kettle")])
    run(fetch=fetch_returning(NOT_FREE), notifier=n, now=NOW, **p)
    assert n.sent == []
    st = run(fetch=fetch_per_asin({DEF: FREE, OTHER: NOT_FREE}), notifier=n,
             now=NOW + timedelta(hours=1), **p)
    assert len(n.sent) == 1
    assert n.sent[0]["click"] == config.product_url(DEF)
    assert st["products"][DEF]["free"] is True
    assert st["products"][OTHER]["free"] is False
    assert [(e["asin"], e["free"]) for e in read_history(tmp_path)] == [
        (DEF, False), (OTHER, False), (DEF, True),
    ]


def test_pushes_carry_a_per_product_tag(tmp_path):
    n = FakeNotifier()
    p = paths(tmp_path, [entry(DEF, "Ladle"), entry(OTHER, "Kettle")])
    run(fetch=fetch_per_asin({DEF: NOT_FREE, OTHER: FREE}), notifier=n, now=NOW, **p)
    assert len(n.sent) == 1
    assert n.sent[0]["title"] == "FREE: Kettle"
    assert n.sent[0]["tags"] == "package,kettle"
    assert n.sent[0]["click"] == config.product_url(OTHER)


def test_a_push_without_a_label_uses_the_page_title(tmp_path):
    n = FakeNotifier()
    p = paths(tmp_path, [entry(OTHER)])
    run(fetch=fetch_returning(FREE), notifier=n, now=NOW, **p)
    assert len(n.sent) == 1
    assert n.sent[0]["title"].startswith("FREE: ")
    assert n.sent[0]["title"] != "FREE: "
    assert n.sent[0]["tags"].startswith("package,")


def test_one_product_failing_keeps_its_data_and_updates_the_other(tmp_path):
    n = FakeNotifier()
    p = paths(tmp_path, [entry(DEF, "Ladle"), entry(OTHER, "Kettle")])
    run(fetch=fetch_returning(NOT_FREE), notifier=n, now=NOW, **p)
    st = run(fetch=fetch_per_asin({DEF: FREE, OTHER: FetchError("boom")}), notifier=n,
             now=NOW + timedelta(hours=1), **p)
    assert st["products"][DEF]["free"] is True
    assert st["products"][DEF]["fail_count"] == 0
    kettle = st["products"][OTHER]
    assert kettle["free"] is False              # last known good reading kept
    assert kettle["fail_count"] == 1
    assert kettle["last_error"] == "boom"
    assert kettle["last_success"] == NOW.isoformat()


def test_all_products_failing_sends_one_combined_warning(tmp_path):
    n = FakeNotifier()
    p = paths(tmp_path, [entry(DEF, "Ladle"), entry(OTHER, "Kettle")])
    for _ in range(3):
        run(fetch=fetch_failing, notifier=n, now=NOW, **p)
    assert len(n.sent) == 1
    assert n.sent[0]["title"] == "Amazon watcher failing"
    assert n.sent[0]["tags"] == "warning"
    assert "All 2 watched products" in n.sent[0]["body"]


def test_one_product_failing_sends_one_tagged_warning(tmp_path):
    n = FakeNotifier()
    p = paths(tmp_path, [entry(DEF, "Ladle"), entry(OTHER, "Kettle")])
    fetch = fetch_per_asin({DEF: NOT_FREE, OTHER: FetchError("boom")})
    for _ in range(3):
        run(fetch=fetch, notifier=n, now=NOW, **p)
    assert len(n.sent) == 1
    assert n.sent[0]["title"] == "Amazon watcher failing: Kettle"
    assert n.sent[0]["tags"] == "warning,kettle"
    assert n.sent[0]["priority"] == "default"


def test_a_handshake_failure_fails_every_product(tmp_path):
    n = FakeNotifier()
    p = paths(tmp_path, [entry(DEF, "Ladle"), entry(OTHER, "Kettle")])
    st = run(fetch=fetch_failing, notifier=n, now=NOW, **p)
    assert st["products"][DEF]["fail_count"] == 1
    assert st["products"][OTHER]["fail_count"] == 1
    assert n.sent == []                          # not yet at the threshold
    assert (tmp_path / "docs" / "index.html").exists()


def test_empty_product_list_writes_the_page_and_sends_nothing(tmp_path):
    n = FakeNotifier()
    p = paths(tmp_path, [])
    st = run(fetch=fetch_returning(FREE), notifier=n, now=NOW, **p)
    assert n.sent == []
    assert st["products"] == {}
    assert st["last_checked"] == NOW.isoformat()
    assert (tmp_path / "docs" / "index.html").exists()


def test_removing_a_product_drops_its_state(tmp_path):
    n = FakeNotifier()
    p = paths(tmp_path, [entry(DEF, "Ladle"), entry(OTHER, "Kettle")])
    st = run(fetch=fetch_returning(NOT_FREE), notifier=n, now=NOW, **p)
    assert sorted(st["products"]) == sorted([DEF, OTHER])
    products.save(p["products_path"], [entry(DEF, "Ladle")])
    st = run(fetch=fetch_returning(NOT_FREE), notifier=n, now=NOW + timedelta(hours=1), **p)
    assert list(st["products"]) == [DEF]
    assert load_state(p["state_path"])["products"].keys() == {DEF}
    # history keeps the record of what happened
    assert {e["asin"] for e in read_history(tmp_path)} == {DEF, OTHER}
