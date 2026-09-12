from watch import notify


class R:
    def __init__(self, status_code=200, text="ok"):
        self.status_code = status_code
        self.text = text


def test_send_posts_to_topic(monkeypatch):
    monkeypatch.setattr(notify.config, "NTFY_SERVER", "https://ntfy.example")
    monkeypatch.setattr(notify.config, "NTFY_TOPIC", "secret-topic")
    monkeypatch.setattr(notify.config, "NTFY_EMAIL", "me@example.com")
    monkeypatch.setattr(notify.config, "NTFY_TOKEN", "")
    calls = []

    def fake_post(url, data=None, headers=None, timeout=None):
        calls.append((url, data, headers))
        return R()

    sent = notify.send("Title here", "body text", click="https://x/y", post=fake_post)
    assert sent is True
    url, data, headers = calls[0]
    assert url == "https://ntfy.example/secret-topic"
    assert data == b"body text"
    assert headers["Title"] == "Title here"
    assert headers["Priority"] == "high"
    assert headers["Click"] == "https://x/y"
    assert headers["Email"] == "me@example.com"
    assert headers["Tags"] == "package,tada"


def test_send_without_email_omits_header(monkeypatch):
    monkeypatch.setattr(notify.config, "NTFY_TOPIC", "t")
    monkeypatch.setattr(notify.config, "NTFY_EMAIL", "")
    monkeypatch.setattr(notify.config, "NTFY_TOKEN", "")
    calls = []

    def fake_post(url, data=None, headers=None, timeout=None):
        calls.append(headers)
        return R()

    notify.send("t", "b", post=fake_post)
    assert "Email" not in calls[0]
    assert "Click" not in calls[0]
    assert "Authorization" not in calls[0]


def test_send_with_token_adds_bearer(monkeypatch):
    monkeypatch.setattr(notify.config, "NTFY_TOPIC", "t")
    monkeypatch.setattr(notify.config, "NTFY_EMAIL", "")
    monkeypatch.setattr(notify.config, "NTFY_TOKEN", "tk_abc")
    calls = []

    def fake_post(url, data=None, headers=None, timeout=None):
        calls.append(headers)
        return R()

    notify.send("t", "b", post=fake_post)
    assert calls[0]["Authorization"] == "Bearer tk_abc"


def test_send_retries_without_email_when_rejected(monkeypatch):
    monkeypatch.setattr(notify.config, "NTFY_TOPIC", "t")
    monkeypatch.setattr(notify.config, "NTFY_EMAIL", "me@example.com")
    monkeypatch.setattr(notify.config, "NTFY_TOKEN", "")
    calls = []

    def fake_post(url, data=None, headers=None, timeout=None):
        calls.append(dict(headers))
        return R(status_code=400 if "Email" in headers else 200)

    assert notify.send("t", "b", post=fake_post) is True
    assert len(calls) == 2
    assert "Email" in calls[0] and "Email" not in calls[1]


def test_send_without_topic_is_noop(monkeypatch):
    monkeypatch.setattr(notify.config, "NTFY_TOPIC", "")
    called = []
    assert notify.send("t", "b", post=lambda *a, **k: called.append(1)) is False
    assert called == []


def test_send_returns_false_on_exception(monkeypatch):
    import requests

    monkeypatch.setattr(notify.config, "NTFY_TOPIC", "t")
    monkeypatch.setattr(notify.config, "NTFY_EMAIL", "")

    def boom(*a, **k):
        raise requests.ConnectionError("down")

    assert notify.send("t", "b", post=boom) is False


def test_send_returns_false_on_unexpected_exception(monkeypatch):
    monkeypatch.setattr(notify.config, "NTFY_TOPIC", "t")
    monkeypatch.setattr(notify.config, "NTFY_EMAIL", "")

    def boom(*a, **k):
        raise UnicodeEncodeError("ascii", "x", 0, 1, "bad")

    assert notify.send("t", "b", post=boom) is False


def test_non_ascii_title_folded_for_headers(monkeypatch):
    monkeypatch.setattr(notify.config, "NTFY_TOPIC", "t")
    monkeypatch.setattr(notify.config, "NTFY_EMAIL", "")
    monkeypatch.setattr(notify.config, "NTFY_TOKEN", "")
    calls = []

    def fake_post(url, data=None, headers=None, timeout=None):
        calls.append((dict(headers), data))
        return R()

    assert notify.send("Café \u05e2\u05d1\u05e8\u05d9\u05ea", "b\u05e2", post=fake_post) is True
    headers, data = calls[0]
    headers["Title"].encode("latin-1")  # would raise if folding failed
    assert headers["Title"].startswith("Cafe")
    assert data == "b\u05e2".encode("utf-8")  # body keeps the original text


def test_no_email_retry_when_server_never_answered(monkeypatch):
    import requests

    monkeypatch.setattr(notify.config, "NTFY_TOPIC", "t")
    monkeypatch.setattr(notify.config, "NTFY_EMAIL", "me@example.com")
    monkeypatch.setattr(notify.config, "NTFY_TOKEN", "")
    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise requests.ConnectionError("down")

    assert notify.send("t", "b", post=boom) is False
    assert len(calls) == 1  # transport failure: no second attempt
