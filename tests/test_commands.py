"""The signed mailbox the status page posts into. No network."""
import json
import time
from datetime import datetime, timezone

from watch import commands, products, state as state_mod

NOW = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)
PHRASE = "basil-ember-kettle-amber-89"
DEF = "B07W1P15GL"
OTHER = "B000000001"


class R:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code


def note(phrase=PHRASE, action="add", product=OTHER, label="Kettle",
         ts=None, nonce="n1", v=1, sig=None):
    cmd = {"action": action, "product": product, "label": label,
           "ts": int(ts if ts is not None else time.time()), "nonce": nonce, "v": v}
    payload = {"cmd": cmd, "sig": sig if sig is not None else commands.sign(phrase, cmd)}
    return {"event": "message", "message": json.dumps(payload)}


def mailbox(*notes):
    """A fake ntfy poll response: one JSON object per line."""
    body = "\n".join(json.dumps(n) for n in notes)
    calls = []

    def get(url, **kw):
        calls.append(url)
        return R(body)
    return get, calls


def recording_post():
    sent = []

    def post(url, data=None, **kw):
        sent.append(json.loads(data.decode("utf-8")))
        return R("", 200)
    return post, sent


def setup(tmp_path, entries=None):
    p = tmp_path / "products.json"
    products.save(p, entries if entries is not None else [
        {"asin": DEF, "label": "Ladle", "added": ""}])
    return p, state_mod.default_state()


# --- derivation and signing ------------------------------------------------


def test_the_topic_is_derived_from_the_passphrase():
    t = commands.topic_for(PHRASE)
    assert t.startswith("amzcmd-")
    assert len(t) == len("amzcmd-") + 24
    assert t == commands.topic_for(PHRASE)          # stable
    assert t != commands.topic_for(PHRASE + "x")    # and unique to the phrase


def test_the_topic_does_not_contain_the_passphrase():
    assert PHRASE not in commands.topic_for(PHRASE)


def test_a_signature_verifies_and_a_tampered_command_does_not():
    cmd = {"action": "add", "product": OTHER, "label": "", "ts": 1, "nonce": "n", "v": 1}
    sig = commands.sign(PHRASE, cmd)
    assert commands.verify(PHRASE, cmd, sig)
    assert not commands.verify(PHRASE + "x", cmd, sig)
    assert not commands.verify(PHRASE, {**cmd, "product": DEF}, sig)
    assert not commands.verify(PHRASE, cmd, "")
    assert not commands.verify(PHRASE, cmd, None)


# --- applying --------------------------------------------------------------


def test_add_changes_the_product_list(tmp_path):
    p, st = setup(tmp_path)
    get, _ = mailbox(note())
    post, sent = recording_post()
    assert commands.apply_commands(PHRASE, p, st, NOW, get=get, post=post) is True
    entries = products.load(p)
    assert [e["asin"] for e in entries] == [DEF, OTHER]
    assert entries[1]["label"] == "Kettle"
    assert sent[0]["ok"] is True and sent[0]["reply"] == "n1"
    assert OTHER in sent[0]["message"]


def test_remove_changes_the_product_list(tmp_path):
    p, st = setup(tmp_path, [{"asin": DEF, "label": "", "added": ""},
                             {"asin": OTHER, "label": "", "added": ""}])
    get, _ = mailbox(note(action="remove", product=OTHER))
    post, sent = recording_post()
    assert commands.apply_commands(PHRASE, p, st, NOW, get=get, post=post) is True
    assert [e["asin"] for e in products.load(p)] == [DEF]
    assert sent[0]["ok"] is True


def test_the_mailbox_url_carries_the_topic_and_window(tmp_path):
    p, st = setup(tmp_path)
    get, calls = mailbox()
    commands.apply_commands(PHRASE, p, st, NOW, get=get, post=recording_post()[0])
    assert commands.topic_for(PHRASE) in calls[0]
    assert f"since={commands.COMMAND_MAX_AGE}s" in calls[0]
    assert "poll=1" in calls[0]


def test_an_empty_passphrase_does_nothing(tmp_path):
    p, st = setup(tmp_path)
    get, calls = mailbox(note())
    assert commands.apply_commands("", p, st, NOW, get=get) is False
    assert calls == []


# --- what is refused -------------------------------------------------------


def test_a_forged_signature_is_ignored(tmp_path):
    p, st = setup(tmp_path)
    get, _ = mailbox(note(sig="deadbeef"))
    post, sent = recording_post()
    assert commands.apply_commands(PHRASE, p, st, NOW, get=get, post=post) is False
    assert [e["asin"] for e in products.load(p)] == [DEF]
    assert sent == []       # an unverified note gets no reply at all


def test_a_command_signed_with_another_passphrase_is_ignored(tmp_path):
    p, st = setup(tmp_path)
    get, _ = mailbox(note(phrase="wrong-phrase"))
    assert commands.apply_commands(PHRASE, p, st, NOW, get=get,
                                   post=recording_post()[0]) is False


def test_a_stale_command_is_ignored(tmp_path):
    p, st = setup(tmp_path)
    get, _ = mailbox(note(ts=time.time() - commands.COMMAND_MAX_AGE - 60))
    assert commands.apply_commands(PHRASE, p, st, NOW, get=get,
                                   post=recording_post()[0]) is False


def test_a_command_from_the_future_is_ignored(tmp_path):
    p, st = setup(tmp_path)
    get, _ = mailbox(note(ts=time.time() + commands.COMMAND_MAX_AGE + 60))
    assert commands.apply_commands(PHRASE, p, st, NOW, get=get,
                                   post=recording_post()[0]) is False


def test_a_replayed_command_is_applied_once(tmp_path):
    p, st = setup(tmp_path)
    get, _ = mailbox(note())
    post, sent = recording_post()
    assert commands.apply_commands(PHRASE, p, st, NOW, get=get, post=post) is True
    # the same note is still inside the window on the next check
    assert commands.apply_commands(PHRASE, p, st, NOW, get=get, post=post) is False
    assert [e["asin"] for e in products.load(p)] == [DEF, OTHER]
    assert len(sent) == 1


def test_an_unknown_version_is_ignored(tmp_path):
    p, st = setup(tmp_path)
    get, _ = mailbox(note(v=2))
    assert commands.apply_commands(PHRASE, p, st, NOW, get=get,
                                   post=recording_post()[0]) is False


def test_noise_on_the_topic_is_ignored(tmp_path):
    p, st = setup(tmp_path)
    get, _ = mailbox({"event": "message", "message": "hello there"},
                     {"event": "keepalive"},
                     {"event": "message", "message": '{"not": "ours"}'})
    assert commands.apply_commands(PHRASE, p, st, NOW, get=get,
                                   post=recording_post()[0]) is False


def test_an_unknown_action_is_refused_with_a_reply(tmp_path):
    p, st = setup(tmp_path)
    get, _ = mailbox(note(action="wipe"))
    post, sent = recording_post()
    assert commands.apply_commands(PHRASE, p, st, NOW, get=get, post=post) is False
    assert sent[0]["ok"] is False and "wipe" in sent[0]["message"]


def test_a_duplicate_product_is_refused_with_a_reply(tmp_path):
    p, st = setup(tmp_path)
    get, _ = mailbox(note(product=DEF))
    post, sent = recording_post()
    assert commands.apply_commands(PHRASE, p, st, NOW, get=get, post=post) is False
    assert sent[0]["ok"] is False and "already being watched" in sent[0]["message"]


def test_a_bad_product_string_is_refused_with_a_reply(tmp_path):
    p, st = setup(tmp_path)
    get, _ = mailbox(note(product="nonsense"))
    post, sent = recording_post()
    assert commands.apply_commands(PHRASE, p, st, NOW, get=get, post=post) is False
    assert sent[0]["ok"] is False and "no ASIN" in sent[0]["message"]


def test_a_refused_command_still_burns_its_nonce(tmp_path):
    """Otherwise a bad note would be answered again on every check for ten minutes."""
    p, st = setup(tmp_path)
    get, _ = mailbox(note(product=DEF))
    post, sent = recording_post()
    commands.apply_commands(PHRASE, p, st, NOW, get=get, post=post)
    commands.apply_commands(PHRASE, p, st, NOW, get=get, post=post)
    assert len(sent) == 1


# --- robustness ------------------------------------------------------------


def test_a_network_failure_is_survived(tmp_path):
    p, st = setup(tmp_path)

    def get(url, **kw):
        raise OSError("connection reset")

    assert commands.apply_commands(PHRASE, p, st, NOW, get=get) is False
    assert [e["asin"] for e in products.load(p)] == [DEF]


def test_a_rate_limit_is_survived(tmp_path):
    p, st = setup(tmp_path)
    assert commands.apply_commands(PHRASE, p, st, NOW,
                                   get=lambda url, **kw: R("too many requests", 429)) is False


def test_a_failing_reply_does_not_lose_the_command(tmp_path):
    p, st = setup(tmp_path)
    get, _ = mailbox(note())

    def post(url, **kw):
        raise OSError("connection reset")

    assert commands.apply_commands(PHRASE, p, st, NOW, get=get, post=post) is True
    assert [e["asin"] for e in products.load(p)] == [DEF, OTHER]


def test_the_nonce_list_stays_capped(tmp_path):
    p, st = setup(tmp_path)
    st["command_nonces"] = [f"old{i}" for i in range(commands.NONCE_MEMORY + 50)]
    get, _ = mailbox(note())
    commands.apply_commands(PHRASE, p, st, NOW, get=get, post=recording_post()[0])
    assert len(st["command_nonces"]) == commands.NONCE_MEMORY
    assert st["command_nonces"][-1] == "n1"


def test_a_flood_is_bounded(tmp_path):
    p, st = setup(tmp_path)
    junk = [{"event": "message", "message": "junk"} for _ in range(500)]
    get, _ = mailbox(*junk, note())
    assert commands.apply_commands(PHRASE, p, st, NOW, get=get,
                                   post=recording_post()[0]) is True


def test_poll_asks_for_a_poll_without_changing_the_list(tmp_path):
    p, st = setup(tmp_path)
    get, _ = mailbox(note(action="poll", product="", label=""))
    post, sent = recording_post()
    assert commands.apply_commands(PHRASE, p, st, NOW, get=get, post=post) is True
    assert [e["asin"] for e in products.load(p)] == [DEF]
    assert sent[0]["ok"] is True and sent[0]["reply"] == "n1"
    assert "poll" in sent[0]["message"].lower()
    assert st["command_nonces"] == ["n1"]
