from datetime import datetime, timezone

from watch import state as state_mod
from watch.render import render_page

NOW = datetime(2026, 9, 12, 10, 30, tzinfo=timezone.utc)


def base_state(free=False):
    st = state_mod.default_state()
    st["last_checked"] = "2026-09-12T10:00:00+00:00"
    st["last_success"] = "2026-09-12T10:00:00+00:00"
    st["product"] = {
        "title": "DI ORO Silicone Ladle <Black>",
        "free": free,
        "delivery_text": "FREE" if free else "ILS 58.91",
        "merchant": "Sold by DI ORO and shipped by Amazon",
        "checked_at": "2026-09-12T10:00:00+00:00",
    }
    return st


def test_paid_state_renders_badge_and_details():
    page = render_page(base_state(free=False), [], NOW)
    assert "Paid shipping" in page
    assert "ILS 58.91" in page
    assert "DI ORO Silicone Ladle &lt;Black&gt;" in page  # escaped
    assert "https://www.amazon.com/dp/B07W1P15GL" in page
    assert "Sold by DI ORO" in page
    assert "2026-09-12 10:00 UTC" in page
    assert '<meta http-equiv="refresh" content="600">' in page


def test_free_state_renders_free_badge():
    page = render_page(base_state(free=True), [], NOW)
    assert "FREE shipping to Israel" in page
    assert "Paid shipping" not in page


def test_no_data_yet():
    page = render_page(state_mod.default_state(), [], NOW)
    assert "No data yet" in page


def test_failure_warning_shown_when_fail_count_positive():
    st = base_state()
    st["fail_count"] = 2
    st["last_error"] = "first GET: captcha page returned"
    page = render_page(st, [], NOW)
    assert "2 consecutive failed polls" in page
    assert "captcha page returned" in page


def test_malformed_timestamp_rendered_verbatim():
    st = base_state()
    st["last_checked"] = "garbage"
    page = render_page(st, [], NOW)
    assert "garbage" in page


def test_history_rows_newest_first():
    hist = [
        {"at": "2026-09-10T08:00:00+00:00", "free": False, "delivery_text": "ILS 58.91"},
        {"at": "2026-09-12T09:00:00+00:00", "free": True, "delivery_text": "FREE"},
    ]
    page = render_page(base_state(free=True), hist, NOW)
    assert page.index("2026-09-12 09:00 UTC") < page.index("2026-09-10 08:00 UTC")
    assert page.count("<tr>") == 3  # header + 2 rows
