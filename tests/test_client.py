import pytest

from watch import client, config
from watch.client import FetchError, fetch_product


class R:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code


class FakeSession:
    """Returns canned responses in order and records every call."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        return self.responses.pop(0)

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        return self.responses.pop(0)


def page(glow="Israel", token="tok123", size=client.MIN_PAGE_CHARS):
    head = (
        '<html><input name="anti-csrftoken-a2z" value="%s">'
        '<span id="glow-ingress-line2" class="nav-line-2">%s</span>' % (token, glow)
    )
    return head + "x" * size + "</html>"


ADDRESS_OK = R('{"isAddressUpdated":1,"successful":1}')


def test_happy_path_returns_second_page_and_posts_address_change():
    second = page(glow="Israel") + "<!-- second -->"
    s = FakeSession([R(page()), ADDRESS_OK, R(second)])
    out = fetch_product("B07W1P15GL", session=s)
    assert out == second
    assert [c[0] for c in s.calls] == ["GET", "POST", "GET"]
    assert s.calls[0][1] == "https://www.amazon.com/dp/B07W1P15GL"
    method, url, kw = s.calls[1]
    assert url == config.ADDRESS_CHANGE_URL
    assert kw["data"]["countryCode"] == "IL"
    assert kw["data"]["locationType"] == "COUNTRY"
    assert kw["headers"]["anti-csrftoken-a2z"] == "tok123"
    assert kw["headers"]["Referer"] == "https://www.amazon.com/dp/B07W1P15GL"
    assert kw["headers"]["X-Requested-With"] == "XMLHttpRequest"


def test_token_regex_matches_json_and_attribute_forms():
    assert client.TOKEN_RE.search('"anti-csrftoken-a2z":"abc+/="').group(1) == "abc+/="
    assert client.TOKEN_RE.search('name="anti-csrftoken-a2z" value="xyz"').group(1) == "xyz"
    assert client.TOKEN_RE.search("&quot;anti-csrftoken-a2z&quot;:&quot;q1&quot;").group(1) == "q1"


def test_non_200_raises():
    s = FakeSession([R(page(), status_code=503)])
    with pytest.raises(FetchError, match="first GET: HTTP 503"):
        fetch_product(session=s)


def test_captcha_page_raises():
    body = "<html><body>Enter the characters you see below (captcha)</body></html>"
    s = FakeSession([R(body)])
    with pytest.raises(FetchError, match="captcha"):
        fetch_product(session=s)


def test_small_body_raises():
    s = FakeSession([R(page(size=100))])
    with pytest.raises(FetchError, match="body too small"):
        fetch_product(session=s)


def test_missing_token_raises():
    body = "<html>" + "x" * client.MIN_PAGE_CHARS + "</html>"
    s = FakeSession([R(body)])
    with pytest.raises(FetchError, match="token"):
        fetch_product(session=s)


def test_address_change_not_updated_raises():
    s = FakeSession([R(page()), R('{"isAddressUpdated":0}')])
    with pytest.raises(FetchError, match="address-change"):
        fetch_product(session=s)


def test_address_change_http_error_raises():
    s = FakeSession([R(page()), R("nope", status_code=400)])
    with pytest.raises(FetchError, match="address-change: HTTP 400"):
        fetch_product(session=s)


def test_glow_not_israel_raises():
    s = FakeSession([R(page()), ADDRESS_OK, R(page(glow="United States"))])
    with pytest.raises(FetchError, match="Israel"):
        fetch_product(session=s)


def test_address_updated_ten_is_not_success():
    s = FakeSession([R(page()), R('{"isAddressUpdated":10}')])
    with pytest.raises(FetchError, match="address-change: not updated"):
        fetch_product(session=s)


def test_address_updated_with_spaces_is_success():
    second = page() + "<!-- second -->"
    s = FakeSession([R(page()), R('{ "isAddressUpdated" : 1, "successful": 1 }'), R(second)])
    assert fetch_product(session=s) == second


def test_every_request_uses_the_shared_timeout():
    s = FakeSession([R(page()), ADDRESS_OK, R(page())])
    fetch_product(session=s)
    assert [kw["timeout"] for _, _, kw in s.calls] == [client.TIMEOUT] * 3


def test_set_israel_does_one_get_and_one_post():
    s = FakeSession([R(page()), ADDRESS_OK])
    assert client.set_israel(s, "B07W1P15GL") is None
    assert [c[0] for c in s.calls] == ["GET", "POST"]
    assert s.calls[1][2]["headers"]["anti-csrftoken-a2z"] == "tok123"


def test_set_israel_does_not_check_the_glow_line():
    """The handshake page may still show the old country; fetch_page is the check."""
    s = FakeSession([R(page(glow="United States")), ADDRESS_OK])
    client.set_israel(s, "B07W1P15GL")


def test_set_israel_raises_without_a_token():
    s = FakeSession([R("<html>" + "x" * client.MIN_PAGE_CHARS + "</html>")])
    with pytest.raises(FetchError, match="token"):
        client.set_israel(s, "B07W1P15GL")


def test_set_israel_raises_when_the_address_is_not_updated():
    s = FakeSession([R(page()), R('{"isAddressUpdated":0}')])
    with pytest.raises(FetchError, match="address-change: not updated"):
        client.set_israel(s, "B07W1P15GL")


def test_fetch_page_does_one_get_and_returns_the_body():
    body = page() + "<!-- only -->"
    s = FakeSession([R(body)])
    assert client.fetch_page(s, "B000000001") == body
    assert [c[0] for c in s.calls] == ["GET"]
    assert s.calls[0][1] == "https://www.amazon.com/dp/B000000001"
    assert s.calls[0][2]["timeout"] == client.TIMEOUT


def test_fetch_page_raises_on_captcha():
    s = FakeSession([R("<html>captcha here</html>")])
    with pytest.raises(FetchError, match="captcha"):
        client.fetch_page(s, "B000000001")


def test_fetch_page_raises_on_a_short_body():
    s = FakeSession([R(page(size=100))])
    with pytest.raises(FetchError, match="body too small"):
        client.fetch_page(s, "B000000001")


def test_fetch_page_names_the_asin_in_its_error():
    s = FakeSession([R(page(), status_code=503)])
    with pytest.raises(FetchError, match="GET B000000001: HTTP 503"):
        client.fetch_page(s, "B000000001")


def test_fetch_page_raises_when_the_glow_line_is_not_israel():
    s = FakeSession([R(page(glow="United States"))])
    with pytest.raises(FetchError, match="Israel"):
        client.fetch_page(s, "B000000001")


def test_one_handshake_then_a_page_per_product():
    """The poll's shape: two requests to set the country, then one per product."""
    s = FakeSession([R(page()), ADDRESS_OK, R(page()), R(page())])
    client.set_israel(s)
    client.fetch_page(s, "B07W1P15GL")
    client.fetch_page(s, "B000000001")
    assert [c[0] for c in s.calls] == ["GET", "POST", "GET", "GET"]
    assert [c[1] for c in s.calls[2:]] == [
        "https://www.amazon.com/dp/B07W1P15GL",
        "https://www.amazon.com/dp/B000000001",
    ]


# --- opening a session: retry the handshake on a fresh session -------------


def sessions_and_factory(*sessions):
    """A session factory handing out `sessions` in order and recording each profile."""
    queue = list(sessions)
    profiles = []

    def factory(profile):
        profiles.append(profile)
        return queue.pop(0)
    return profiles, factory


def test_open_israel_session_returns_the_first_session_when_the_handshake_works():
    good = FakeSession([R(page()), ADDRESS_OK])
    profiles, factory = sessions_and_factory(good)
    slept = []
    assert client.open_israel_session(session_factory=factory, sleep=slept.append) is good
    assert profiles == [client.HANDSHAKE_PROFILES[0]]
    assert slept == []


def test_open_israel_session_retries_on_a_fresh_session_with_another_profile():
    blocked = FakeSession([R("<html>captcha</html>")])
    good = FakeSession([R(page()), ADDRESS_OK])
    profiles, factory = sessions_and_factory(blocked, good)
    slept = []
    assert client.open_israel_session(session_factory=factory, sleep=slept.append) is good
    assert profiles == list(client.HANDSHAKE_PROFILES[:2])
    assert profiles[0] != profiles[1]
    assert slept == [client.HANDSHAKE_BACKOFF[0]]
    assert [c[0] for c in blocked.calls] == ["GET"]      # the blocked session is dropped


def test_open_israel_session_raises_the_last_error_after_every_profile_failed():
    sessions = [FakeSession([R("<html>captcha</html>")]) for _ in client.HANDSHAKE_PROFILES]
    sessions[-1] = FakeSession([R(page()), R('{"isAddressUpdated":0}')])
    profiles, factory = sessions_and_factory(*sessions)
    slept = []
    with pytest.raises(FetchError, match="address-change: not updated"):
        client.open_israel_session(session_factory=factory, sleep=slept.append)
    assert profiles == list(client.HANDSHAKE_PROFILES)
    assert slept == list(client.HANDSHAKE_BACKOFF)        # no sleep after the last attempt


def test_handshake_profiles_and_backoff_line_up():
    assert len(client.HANDSHAKE_PROFILES) >= 2
    assert len(client.HANDSHAKE_BACKOFF) == len(client.HANDSHAKE_PROFILES) - 1
    assert all(b > 0 for b in client.HANDSHAKE_BACKOFF)
