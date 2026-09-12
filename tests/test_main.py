"""One poll cycle with fake fetch and fake notifier. No network."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from watch import config
from watch.client import FetchError
from watch.main import run
from watch.state import load as load_state

FIX = Path(__file__).parent / "fixtures"
NOT_FREE = (FIX / "not_free.html").read_text(encoding="utf-8")
FREE = (FIX / "free.html").read_text(encoding="utf-8")
NOW = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def __call__(self, title, body, click=None, priority="high", tags=""):
        self.sent.append({"title": title, "body": body, "click": click, "priority": priority, "tags": tags})
        return True


def fetch_returning(html):
    return lambda asin: html


def fetch_failing(asin):
    raise FetchError("first GET: captcha page returned")


def paths(tmp_path):
    return dict(
        state_path=tmp_path / "state.json",
        history_path=tmp_path / "history.json",
        page_path=tmp_path / "docs" / "index.html",
    )


def test_first_poll_records_without_push(tmp_path):
    n = FakeNotifier()
    st = run(fetch=fetch_returning(NOT_FREE), notifier=n, now=NOW, **paths(tmp_path))
    assert n.sent == []
    assert st["product"]["free"] is False
    assert st["product"]["checked_at"] == NOW.isoformat()
    assert st["last_success"] == NOW.isoformat()
    assert st["fail_count"] == 0
    assert (tmp_path / "docs" / "index.html").exists()
    assert load_state(tmp_path / "state.json") == st
    import json
    hist = json.loads((tmp_path / "history.json").read_text(encoding="utf-8"))
    assert len(hist) == 1 and hist[0]["free"] is False


def test_paid_to_free_pushes_once(tmp_path):
    n = FakeNotifier()
    p = paths(tmp_path)
    run(fetch=fetch_returning(NOT_FREE), notifier=n, now=NOW, **p)
    run(fetch=fetch_returning(FREE), notifier=n, now=NOW + timedelta(hours=1), **p)
    assert len(n.sent) == 1
    msg = n.sent[0]
    assert msg["title"] == "Amazon: free shipping to Israel!"
    assert msg["click"] == config.PRODUCT_URL
    assert msg["priority"] == "high"
    assert "FREE" in msg["body"]
    # stays free: no second push
    run(fetch=fetch_returning(FREE), notifier=n, now=NOW + timedelta(hours=2), **p)
    assert len(n.sent) == 1


def test_free_to_paid_records_history_without_push(tmp_path):
    import json
    n = FakeNotifier()
    p = paths(tmp_path)
    run(fetch=fetch_returning(FREE), notifier=n, now=NOW, **p)
    assert len(n.sent) == 1  # already free on the first observation: announced once
    run(fetch=fetch_returning(NOT_FREE), notifier=n, now=NOW + timedelta(hours=1), **p)
    assert len(n.sent) == 1  # falling back to paid adds no push
    hist = json.loads((tmp_path / "history.json").read_text(encoding="utf-8"))
    assert [e["free"] for e in hist] == [True, False]


def test_first_poll_pushes_when_already_free(tmp_path):
    n = FakeNotifier()
    st = run(fetch=fetch_returning(FREE), notifier=n, now=NOW, **paths(tmp_path))
    assert len(n.sent) == 1
    assert n.sent[0]["title"] == "Amazon: free shipping to Israel!"
    assert n.sent[0]["click"] == config.PRODUCT_URL
    assert n.sent[0]["priority"] == "high"
    assert st["product"]["free"] is True


def test_lost_state_file_re_announces_free(tmp_path):
    n = FakeNotifier()
    p = paths(tmp_path)
    run(fetch=fetch_returning(FREE), notifier=n, now=NOW, **p)
    Path(p["state_path"]).unlink()
    run(fetch=fetch_returning(FREE), notifier=n, now=NOW + timedelta(hours=1), **p)
    assert len(n.sent) == 2


def test_unchanged_state_adds_no_history(tmp_path):
    import json
    n = FakeNotifier()
    p = paths(tmp_path)
    run(fetch=fetch_returning(NOT_FREE), notifier=n, now=NOW, **p)
    run(fetch=fetch_returning(NOT_FREE), notifier=n, now=NOW + timedelta(hours=1), **p)
    hist = json.loads((tmp_path / "history.json").read_text(encoding="utf-8"))
    assert len(hist) == 1


def test_failures_alert_once_at_threshold_and_reset(tmp_path):
    n = FakeNotifier()
    p = paths(tmp_path)
    for i in range(1, 5):
        st = run(fetch=fetch_failing, notifier=n, now=NOW, **p)
        assert st["fail_count"] == i
        assert "captcha" in st["last_error"]
    assert len(n.sent) == 1
    assert n.sent[0]["title"] == "Amazon watcher failing"
    assert n.sent[0]["priority"] == "default"
    st = run(fetch=fetch_returning(NOT_FREE), notifier=n, now=NOW, **p)
    assert st["fail_count"] == 0
    assert st["last_error"] is None


def test_failures_rewarn_every_24_polls(tmp_path):
    n = FakeNotifier()
    p = paths(tmp_path)
    for i in range(1, 28):
        run(fetch=fetch_failing, notifier=n, now=NOW, **p)
    assert len(n.sent) == 2
    assert all(msg["title"] == "Amazon watcher failing" for msg in n.sent)


def test_failure_keeps_previous_product(tmp_path):
    n = FakeNotifier()
    p = paths(tmp_path)
    run(fetch=fetch_returning(FREE), notifier=n, now=NOW, **p)
    st = run(fetch=fetch_failing, notifier=n, now=NOW + timedelta(hours=1), **p)
    assert st["product"]["free"] is True
    assert st["last_checked"] == (NOW + timedelta(hours=1)).isoformat()
    assert st["last_success"] == NOW.isoformat()
    page = (tmp_path / "docs" / "index.html").read_text(encoding="utf-8")
    assert "1 consecutive failed polls" in page


def test_parse_error_counts_as_failure(tmp_path):
    n = FakeNotifier()
    st = run(fetch=fetch_returning("<html>no delivery block</html>"), notifier=n, now=NOW, **paths(tmp_path))
    assert st["fail_count"] == 1
    assert "delivery block" in st["last_error"]
