"""The status page: one card per product, plus the global block. No network."""
from datetime import datetime, timezone

from watch import config, state as state_mod
from watch.render import render_page

NOW = datetime(2026, 9, 12, 10, 30, tzinfo=timezone.utc)

DEF = config.DEFAULT_ASIN
OTHER = "B000000001"


def entry(asin=DEF, label=""):
    return {"asin": asin, "label": label, "added": ""}


def base_state(free=False, asin=DEF):
    st = state_mod.default_state()
    st["last_checked"] = "2026-09-12T10:00:00+00:00"
    e = state_mod.entry(st, asin)
    e.update({
        "title": "DI ORO Silicone Ladle <Black>",
        "free": free,
        "delivery_text": "FREE" if free else "ILS 58.91",
        "merchant": "Sold by DI ORO and shipped by Amazon",
        "checked_at": "2026-09-12T10:00:00+00:00",
        "last_success": "2026-09-12T10:00:00+00:00",
    })
    return st


def test_paid_state_renders_badge_and_details():
    page = render_page(base_state(free=False), [], [entry()], NOW)
    assert "Paid shipping" in page
    assert "ILS 58.91" in page
    assert "DI ORO Silicone Ladle &lt;Black&gt;" in page  # escaped
    assert "https://www.amazon.com/dp/B07W1P15GL" in page
    assert "Sold by DI ORO" in page
    assert "2026-09-12 13:00 (10:00 UTC)" in page  # Jerusalem time beside UTC
    assert '<meta http-equiv="refresh" content="600">' in page


def test_free_state_renders_free_badge():
    page = render_page(base_state(free=True), [], [entry()], NOW)
    assert "FREE shipping to Israel" in page
    assert "Paid shipping" not in page


def test_no_data_yet():
    page = render_page(state_mod.default_state(), [], [entry()], NOW)
    assert "No data yet" in page


def test_a_watched_product_with_no_state_entry_renders_as_unknown():
    """products.json can name a product the poll has not reached yet."""
    page = render_page(base_state(), [], [entry(), entry(OTHER, "Kettle")], NOW)
    assert "No data yet" in page
    assert "Kettle" in page


def test_failure_warning_shown_on_its_own_card():
    st = base_state()
    st["products"][DEF]["fail_count"] = 2
    st["products"][DEF]["last_error"] = "first GET: captcha page returned"
    e = state_mod.entry(st, OTHER)
    e.update({"free": False, "title": "Kettle", "delivery_text": "$5.00"})
    page = render_page(st, [], [entry(), entry(OTHER, "Kettle")], NOW)
    assert page.count("consecutive failed polls") == 1
    assert "2 consecutive failed polls" in page
    assert "captcha page returned" in page


def test_malformed_timestamp_rendered_verbatim():
    st = base_state()
    st["last_checked"] = "garbage"
    page = render_page(st, [], [entry()], NOW)
    assert "garbage" in page
    assert "Next automatic check" not in page


def test_history_rows_newest_first():
    hist = [
        {"at": "2026-09-10T08:00:00+00:00", "asin": DEF, "free": False,
         "delivery_text": "ILS 58.91"},
        {"at": "2026-09-12T09:00:00+00:00", "asin": DEF, "free": True, "delivery_text": "FREE"},
    ]
    page = render_page(base_state(free=True), hist, [entry()], NOW)
    assert page.index("2026-09-12 12:00") < page.index("2026-09-10 11:00")
    assert page.count("<tr>") == 3  # header + 2 rows


def test_check_now_button_links_to_the_workflow():
    page = render_page(base_state(), [], [entry()], NOW)
    assert "Check now" in page
    assert 'href="https://github.com/Yanik1983/amazon-watch/actions/workflows/poll.yml"' in page


def test_the_manage_workflow_is_linked_as_a_fallback():
    page = render_page(base_state(), [], [entry()], NOW)
    assert f'href="{config.MANAGE_WORKFLOW_URL}"' in page
    assert "choose add or remove" in page


def test_next_check_line_is_one_interval_after_the_last_one():
    page = render_page(base_state(), [], [entry()], NOW)
    # last_checked is 10:00 UTC = 13:00 Jerusalem; the interval is one hour
    assert "Next automatic check: about 2026-09-12 14:00" in page


def test_no_next_check_line_before_the_first_poll():
    page = render_page(state_mod.default_state(), [], [entry()], NOW)
    assert "Next automatic check" not in page


# --- several products ------------------------------------------------------


def two_product_state():
    st = base_state(free=False)                      # the Ladle is paid
    e = state_mod.entry(st, OTHER)
    e.update({
        "title": "Electric Kettle",
        "free": True,
        "delivery_text": "FREE",
        "merchant": "",
        "checked_at": "2026-09-12T10:00:00+00:00",
        "last_success": "2026-09-12T10:00:00+00:00",
    })
    return st


def test_a_card_per_product():
    page = render_page(two_product_state(), [],
                       [entry(DEF, "Ladle"), entry(OTHER, "Kettle")], NOW)
    assert page.count('<div class="card">') == 2
    assert "Ladle" in page and "Kettle" in page
    assert "FREE shipping to Israel" in page
    assert "Paid shipping" in page


def test_free_products_sort_first():
    page = render_page(two_product_state(), [],
                       [entry(DEF, "Ladle"), entry(OTHER, "Kettle")], NOW)
    assert page.index("Kettle") < page.index("Ladle")


def test_a_card_shows_its_own_history_only():
    hist = [
        {"at": "2026-09-10T08:00:00+00:00", "asin": DEF, "free": False,
         "delivery_text": "ILS 58.91"},
        {"at": "2026-09-11T08:00:00+00:00", "asin": OTHER, "free": True,
         "delivery_text": "KETTLE FREE"},
    ]
    page = render_page(two_product_state(), hist,
                       [entry(DEF, "Ladle"), entry(OTHER, "Kettle")], NOW)
    assert page.count("<tr>") == 4  # two headers, one row each
    kettle_card = page[page.index("Kettle"):page.index("Ladle")]
    assert "KETTLE FREE" in kettle_card
    assert "ILS 58.91" not in kettle_card


def test_labels_fall_back_to_the_page_title():
    page = render_page(two_product_state(), [], [entry(DEF), entry(OTHER)], NOW)
    assert "DI ORO Silicone Ladle &lt;Black&gt;" in page
    assert "Electric Kettle" in page


def test_an_empty_product_list_still_renders_the_buttons():
    page = render_page(state_mod.default_state(), [], [], NOW)
    assert "No products are being watched." in page
    assert "Check now" in page
    assert 'id="cmd-form"' in page          # the form works with an empty list too
    assert '<div class="card">' not in page


# --- the add/remove form ---------------------------------------------------


def page_with_form():
    return render_page(base_state(), [], [entry()], NOW)


def test_the_form_is_present():
    page = page_with_form()
    assert 'id="cmd-form"' in page
    assert 'id="cmd-product"' in page
    assert 'id="cmd-phrase"' in page
    assert 'value="add"' in page and 'value="remove"' in page


def test_the_page_carries_no_secret():
    """The page is public, so it must hold neither a credential nor the mailbox address."""
    from watch import commands
    page = page_with_form()
    assert "amzcmd-" not in page.replace('"amzcmd-" + ', "")  # only the derivation, no address
    assert commands.topic_for("basil-ember-kettle-amber-89") not in page
    assert "ghp_" not in page and "github_pat_" not in page
    assert "token" not in page.lower()


def test_the_form_talks_only_to_ntfy():
    page = page_with_form()
    assert config.NTFY_SERVER in page
    assert "api.github.com" not in page


def test_the_manage_workflow_stays_as_a_fallback():
    page = page_with_form()
    assert "Lost the passphrase?" in page
    assert config.MANAGE_WORKFLOW_URL in page


def test_the_script_uses_the_same_command_version_as_the_watcher():
    from watch import commands
    assert f"VERSION = {commands.COMMAND_VERSION}" in page_with_form()


def test_each_card_shows_its_asin():
    page = render_page(two_product_state(), [],
                       [entry(DEF, "Ladle"), entry(OTHER, "Kettle")], NOW)
    assert f'<p class="asin">{DEF}</p>' in page
    assert f'<p class="asin">{OTHER}</p>' in page


def test_the_asin_is_shown_even_without_a_reading():
    """A product added a moment ago has no data yet but still needs its identity."""
    page = render_page(state_mod.default_state(), [], [entry(OTHER, "Kettle")], NOW)
    assert f'<p class="asin">{OTHER}</p>' in page


def test_the_page_does_not_depend_on_the_render_time():
    """Every tick re-renders, so an unchanged page must produce identical bytes."""
    from datetime import timedelta
    st, hist, prods = base_state(), [], [entry()]
    assert render_page(st, hist, prods, NOW) == render_page(
        st, hist, prods, NOW + timedelta(hours=5))


def test_next_check_line_uses_the_retry_interval_while_everything_fails():
    st = base_state()
    for e in st["products"].values():
        e["fail_count"] = 3
        e["last_error"] = "GET: captcha page returned"
    page = render_page(st, [], [entry()], NOW)
    # 10:00 UTC = 13:00 Jerusalem; the retry interval is 15 minutes, not an hour
    assert "Next automatic check: about 2026-09-12 13:15" in page
    assert "14:00" not in page
