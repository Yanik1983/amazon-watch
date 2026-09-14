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


# --- ticks: the mailbox every minute, Amazon once an hour ------------------


def no_mailbox(url, **kw):
    """A mailbox that is always empty."""
    class R:
        status_code = 200
        text = ""
    return R()


def tick_paths(tmp_path, entries=None):
    p = paths(tmp_path, entries)
    p.pop("history_path")  # tick passes the rest through to run()
    return p


def test_a_tick_polls_when_no_poll_has_ever_run(tmp_path):
    from watch.main import tick
    n = FakeNotifier()
    st = tick(passphrase="", fetch=fetch_returning(NOT_FREE), notifier=n, now=NOW,
              get=no_mailbox, history_path=tmp_path / "history.json",
              **tick_paths(tmp_path))
    assert st["last_checked"] == NOW.isoformat()
    assert st["products"][DEF]["free"] is False


def test_a_tick_inside_the_interval_does_not_poll(tmp_path):
    from watch.main import tick
    n = FakeNotifier()
    p = tick_paths(tmp_path)
    hp = tmp_path / "history.json"
    tick(passphrase="", fetch=fetch_returning(NOT_FREE), notifier=n, now=NOW,
         get=no_mailbox, history_path=hp, **p)

    def must_not_run(asin):
        raise AssertionError("Amazon was polled inside the interval")

    st = tick(passphrase="", fetch=must_not_run, notifier=n,
              now=NOW + timedelta(minutes=30), get=no_mailbox, history_path=hp, **p)
    assert st["last_checked"] == NOW.isoformat()  # unchanged


def test_a_tick_after_the_interval_polls_again(tmp_path):
    from watch.main import tick
    n = FakeNotifier()
    p = tick_paths(tmp_path)
    hp = tmp_path / "history.json"
    tick(passphrase="", fetch=fetch_returning(NOT_FREE), notifier=n, now=NOW,
         get=no_mailbox, history_path=hp, **p)
    later = NOW + timedelta(hours=1)
    st = tick(passphrase="", fetch=fetch_returning(FREE), notifier=n, now=later,
              get=no_mailbox, history_path=hp, **p)
    assert st["last_checked"] == later.isoformat()
    assert len(n.sent) == 1


def test_a_command_forces_a_poll_on_the_same_tick(tmp_path):
    """Adding a product from the page must show it without waiting for the hour."""
    import json as _json
    import time as _time
    from watch import commands
    from watch.main import tick

    phrase = "test-phrase"
    cmd = {"action": "add", "product": OTHER, "label": "Kettle",
           "ts": int(_time.time()), "nonce": "abc", "v": 1}
    body = _json.dumps({"cmd": cmd, "sig": commands.sign(phrase, cmd)})

    def mailbox(url, **kw):
        class R:
            status_code = 200
            text = _json.dumps({"event": "message", "message": body})
        return R()

    n = FakeNotifier()
    p = tick_paths(tmp_path, [entry(DEF, "Ladle")])
    hp = tmp_path / "history.json"
    tick(passphrase=phrase, fetch=fetch_returning(NOT_FREE), notifier=n, now=NOW,
         get=no_mailbox, post=lambda *a, **k: None, history_path=hp, **p)

    # well inside the hour, but a command landed
    later = NOW + timedelta(minutes=5)
    st = tick(passphrase=phrase, fetch=fetch_returning(NOT_FREE), notifier=n, now=later,
              get=mailbox, post=lambda *a, **k: None, history_path=hp, **p)
    assert st["last_checked"] == later.isoformat()
    assert sorted(st["products"]) == sorted([DEF, OTHER])
    assert st["command_nonces"] == ["abc"]


def test_a_tick_with_no_passphrase_never_reads_the_mailbox(tmp_path):
    from watch.main import tick

    def must_not_run(url, **kw):
        raise AssertionError("the mailbox was read without a passphrase")

    tick(passphrase="", fetch=fetch_returning(NOT_FREE), notifier=FakeNotifier(),
         now=NOW, get=must_not_run, history_path=tmp_path / "history.json",
         **tick_paths(tmp_path))


def test_poll_due_waits_the_full_interval_when_healthy():
    from watch.main import poll_due
    st = {"last_checked": NOW.isoformat(),
          "products": {DEF: {"fail_count": 0}, OTHER: {"fail_count": 0}}}
    assert poll_due(st, NOW + timedelta(seconds=config.POLL_INTERVAL_SECONDS - 1)) is False
    assert poll_due(st, NOW + timedelta(seconds=config.POLL_INTERVAL_SECONDS)) is True


def test_poll_due_retries_sooner_when_everything_failed():
    from watch.main import poll_due
    st = {"last_checked": NOW.isoformat(),
          "products": {DEF: {"fail_count": 2}, OTHER: {"fail_count": 1}}}
    assert poll_due(st, NOW + timedelta(seconds=config.RETRY_INTERVAL_SECONDS - 1)) is False
    assert poll_due(st, NOW + timedelta(seconds=config.RETRY_INTERVAL_SECONDS)) is True


def test_poll_due_keeps_the_full_interval_when_one_product_still_works():
    from watch.main import poll_due
    st = {"last_checked": NOW.isoformat(),
          "products": {DEF: {"fail_count": 0}, OTHER: {"fail_count": 5}}}
    assert poll_due(st, NOW + timedelta(seconds=config.RETRY_INTERVAL_SECONDS)) is False


def test_poll_due_on_a_first_run_or_a_broken_timestamp():
    from watch.main import poll_due
    assert poll_due({}, NOW) is True
    assert poll_due({"last_checked": "garbage"}, NOW) is True


def test_poll_due_with_no_products_uses_the_full_interval():
    from watch.main import poll_due
    st = {"last_checked": NOW.isoformat(), "products": {}}
    assert poll_due(st, NOW + timedelta(seconds=config.RETRY_INTERVAL_SECONDS)) is False


def test_a_tick_without_a_poll_still_renders_the_page(tmp_path):
    """A page change must appear within a minute, not at the next hourly poll."""
    from watch.main import tick
    n = FakeNotifier()
    p = tick_paths(tmp_path)
    hp = tmp_path / "history.json"
    page = tmp_path / "docs" / "index.html"
    tick(passphrase="", fetch=fetch_returning(NOT_FREE), notifier=n, now=NOW,
         get=no_mailbox, history_path=hp, **p)
    page.unlink()
    tick(passphrase="", fetch=fetch_returning(NOT_FREE), notifier=n,
         now=NOW + timedelta(minutes=5), get=no_mailbox, history_path=hp, **p)
    assert page.exists()
    assert "DI ORO" in page.read_text(encoding="utf-8")


def test_an_unchanged_tick_rewrites_the_page_byte_for_byte(tmp_path):
    """Otherwise every tick would commit and push a change."""
    from watch.main import tick
    n = FakeNotifier()
    p = tick_paths(tmp_path)
    hp = tmp_path / "history.json"
    page = tmp_path / "docs" / "index.html"
    tick(passphrase="", fetch=fetch_returning(NOT_FREE), notifier=n, now=NOW,
         get=no_mailbox, history_path=hp, **p)
    before = page.read_text(encoding="utf-8")
    tick(passphrase="", fetch=fetch_returning(NOT_FREE), notifier=n,
         now=NOW + timedelta(minutes=7), get=no_mailbox, history_path=hp, **p)
    assert page.read_text(encoding="utf-8") == before


# --- asking the workflow for a fresh runner when Amazon keeps blocking -----


def failing_state(*fail_counts, checked=NOW):
    asins = [DEF, OTHER, "B000000002"][: len(fail_counts)]
    return {
        "last_checked": checked.isoformat(),
        "products": {a: {"fail_count": f} for a, f in zip(asins, fail_counts)},
    }


def test_restart_wanted_after_two_all_failed_polls():
    from watch.main import restart_wanted
    assert restart_wanted(failing_state(2, 3), NOW) is True


def test_restart_not_wanted_after_a_single_failed_poll():
    from watch.main import restart_wanted
    assert restart_wanted(failing_state(1, 1), NOW) is False


def test_restart_not_wanted_while_one_product_still_works():
    from watch.main import restart_wanted
    assert restart_wanted(failing_state(5, 0), NOW) is False


def test_restart_not_wanted_when_this_tick_did_not_poll():
    from watch.main import restart_wanted
    earlier = NOW - timedelta(minutes=5)
    assert restart_wanted(failing_state(4, 4, checked=earlier), NOW) is False


def test_restart_not_wanted_with_nothing_watched():
    from watch.main import restart_wanted
    assert restart_wanted({"last_checked": NOW.isoformat(), "products": {}}, NOW) is False


def test_tick_main_exits_with_the_restart_code_when_a_restart_is_wanted(monkeypatch):
    from watch import main

    def fake_tick(now=None, **kw):
        return failing_state(2, 2, checked=now)
    monkeypatch.setattr(main, "tick", fake_tick)
    assert main.tick_main() == main.EXIT_RESTART


def test_tick_main_exits_zero_when_the_poll_is_healthy(monkeypatch):
    from watch import main

    def fake_tick(now=None, **kw):
        return failing_state(0, 0, checked=now)
    monkeypatch.setattr(main, "tick", fake_tick)
    assert main.tick_main() == 0


def test_the_real_fetcher_opens_one_retrying_session(tmp_path, monkeypatch):
    from watch import main
    from tests.test_client import FakeSession, R, page
    opened = []

    def fake_open():
        # The fixture is a fragment; page() adds the glow line fetch_page insists on.
        s = FakeSession([R(page() + NOT_FREE), R(page() + NOT_FREE)])
        opened.append(s)
        return s
    monkeypatch.setattr(main, "open_israel_session", fake_open)
    p = paths(tmp_path, [entry(DEF, "Ladle"), entry(OTHER, "Kettle")])
    st = run(fetch=None, notifier=FakeNotifier(), now=NOW, **p)
    assert len(opened) == 1
    assert [c[0] for c in opened[0].calls] == ["GET", "GET"]
    assert st["products"][DEF]["fail_count"] == 0
    assert st["products"][OTHER]["fail_count"] == 0


def test_the_real_fetcher_reopens_the_session_when_a_product_page_is_a_captcha(tmp_path, monkeypatch):
    """The handshake can pass and the next page still be a captcha: retry that
    product once on a fresh session rather than counting it failed."""
    from watch import main
    from tests.test_client import FakeSession, R, page
    good = page() + NOT_FREE
    opened = []

    def fake_open():
        first = not opened
        s = FakeSession([R("<html>captcha</html>")] if first else [R(good), R(good)])
        opened.append(s)
        return s
    monkeypatch.setattr(main, "open_israel_session", fake_open)
    p = paths(tmp_path, [entry(DEF, "Ladle"), entry(OTHER, "Kettle")])
    st = run(fetch=None, notifier=FakeNotifier(), now=NOW, **p)
    assert len(opened) == 2
    assert [c[0] for c in opened[0].calls] == ["GET"]
    assert [c[0] for c in opened[1].calls] == ["GET", "GET"]   # retry, then the next product
    assert st["products"][DEF]["fail_count"] == 0
    assert st["products"][OTHER]["fail_count"] == 0


def test_the_real_fetcher_gives_up_on_a_product_after_one_reopen(tmp_path, monkeypatch):
    from watch import main
    from tests.test_client import FakeSession, R, page
    good = page() + NOT_FREE
    opened = []

    def fake_open():
        s = FakeSession([R("<html>captcha</html>"), R(good)])
        opened.append(s)
        return s
    monkeypatch.setattr(main, "open_israel_session", fake_open)
    p = paths(tmp_path, [entry(DEF, "Ladle"), entry(OTHER, "Kettle")])
    st = run(fetch=None, notifier=FakeNotifier(), now=NOW, **p)
    assert len(opened) == 2
    assert st["products"][DEF]["fail_count"] == 1
    assert "captcha" in st["products"][DEF]["last_error"]
    assert st["products"][OTHER]["fail_count"] == 0     # served by the second session


def test_the_real_fetcher_does_not_reopen_for_a_non_captcha_error(tmp_path, monkeypatch):
    from watch import main
    from tests.test_client import FakeSession, R, page
    opened = []

    def fake_open():
        s = FakeSession([R(page(), status_code=503), R(page() + NOT_FREE)])
        opened.append(s)
        return s
    monkeypatch.setattr(main, "open_israel_session", fake_open)
    p = paths(tmp_path, [entry(DEF, "Ladle"), entry(OTHER, "Kettle")])
    st = run(fetch=None, notifier=FakeNotifier(), now=NOW, **p)
    assert len(opened) == 1
    assert st["products"][DEF]["fail_count"] == 1
    assert st["products"][OTHER]["fail_count"] == 0


# --- stopping the job from the page ----------------------------------------


def signed_mailbox(phrase, action, nonce="stop1"):
    import json as _json
    import time as _time
    from watch import commands
    cmd = {"action": action, "product": "", "label": "",
           "ts": int(_time.time()), "nonce": nonce, "v": 1}
    body = _json.dumps({"cmd": cmd, "sig": commands.sign(phrase, cmd)})

    def mailbox(url, **kw):
        class R:
            status_code = 200
            text = _json.dumps({"event": "message", "message": body})
        return R()
    return mailbox


def test_a_stop_note_ends_the_tick_without_polling(tmp_path):
    from watch.main import tick

    def must_not_run(asin):
        raise AssertionError("Amazon was polled on a stop tick")

    p = tick_paths(tmp_path, [entry(DEF, "Ladle")])
    st = tick(passphrase="pw", fetch=must_not_run, notifier=FakeNotifier(), now=NOW,
              get=signed_mailbox("pw", "stop"), post=lambda *a, **k: None,
              history_path=tmp_path / "history.json", **p)
    assert st["stop_requested"] is True
    assert st["last_checked"] is None
    saved = load_state(p["state_path"])
    assert saved["command_nonces"] == ["stop1"]      # the note is not applied twice
    assert "stop_requested" not in saved             # the next job must start normally


def test_tick_main_exits_with_the_stop_code_on_a_stop_note(monkeypatch):
    from watch import main

    def fake_tick(now=None, **kw):
        return {"last_checked": None, "products": {}, "stop_requested": True}
    monkeypatch.setattr(main, "tick", fake_tick)
    assert main.tick_main() == main.EXIT_STOP
    assert main.EXIT_STOP not in (0, main.EXIT_RESTART)

