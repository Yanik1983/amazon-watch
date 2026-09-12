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
