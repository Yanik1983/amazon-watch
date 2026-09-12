"""A signed mailbox on ntfy, so the status page can change the watched products.

The status page is static HTML on GitHub Pages with no server of its own, and a
credential placed in a public page is readable by anyone who opens it. So the
page holds nothing secret: it asks the user for a passphrase, derives the mailbox
address and a signature from it, and drops a note in. The poll job, which is
already running around the clock, checks that mailbox once a minute and acts on
notes it can verify.

The passphrase never travels. Both the topic name and the signature are HMACs of
it, so reading the topic reveals neither, and a note cannot be forged without it.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from datetime import datetime
from pathlib import Path

import requests

from watch import config, products

log = logging.getLogger(__name__)

COMMAND_VERSION = 1
COMMAND_MAX_AGE = 600     # seconds a note stays valid, which also bounds replay risk
NONCE_MEMORY = 200        # nonces remembered; far more than COMMAND_MAX_AGE can hold
FETCH_LIMIT = 50          # notes read per check, so a flooded topic cannot stall the poll
TIMEOUT = 15


def _hmac(passphrase: str, message: bytes) -> str:
    return hmac.new(passphrase.encode("utf-8"), message, hashlib.sha256).hexdigest()


def topic_for(passphrase: str) -> str:
    """The mailbox address for this passphrase.

    Derived rather than configured, so the address never appears in the page
    source and a stranger reading the page cannot find the mailbox at all.
    """
    return "amzcmd-" + _hmac(passphrase, b"topic")[:24]


def _canonical(cmd: dict) -> bytes:
    return "\n".join([
        str(cmd.get("action", "")),
        str(cmd.get("product", "")),
        str(cmd.get("label", "")),
        str(cmd.get("ts", "")),
        str(cmd.get("nonce", "")),
    ]).encode("utf-8")


def sign(passphrase: str, cmd: dict) -> str:
    return _hmac(passphrase, _canonical(cmd))


def verify(passphrase: str, cmd: dict, sig: str) -> bool:
    return hmac.compare_digest(sign(passphrase, cmd), str(sig or ""))


def _reply(post, topic: str, nonce: str, ok: bool, message: str) -> None:
    """Tell the page what happened. Advisory only; nothing acts on a reply."""
    body = json.dumps({"reply": nonce, "ok": ok, "message": message})
    try:
        post(f"{config.NTFY_SERVER}/{topic}", data=body.encode("utf-8"), timeout=TIMEOUT)
    except Exception as e:  # a reply that does not arrive costs only the page's message
        log.warning("could not post command reply: %s", e)


def _notes(get, topic: str, since: int) -> list[dict]:
    url = f"{config.NTFY_SERVER}/{topic}/json?poll=1&since={since}s"
    resp = get(url, timeout=TIMEOUT)
    if getattr(resp, "status_code", 0) != 200:
        log.warning("mailbox returned %s; skipping this check", resp.status_code)
        return []
    out = []
    for line in (resp.text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out[-FETCH_LIMIT:]


def apply_commands(
    passphrase: str,
    products_path: str | Path,
    state: dict,
    now: datetime,
    get=requests.get,
    post=requests.post,
) -> bool:
    """Act on any verified notes in the mailbox. Returns True if the list changed.

    Never raises. The mailbox is a convenience; a network failure, a rate limit or
    a flood of junk must not stop the watcher from watching.
    """
    if not passphrase:
        return False
    topic = topic_for(passphrase)
    try:
        # Always read the whole validity window rather than tracking a cursor in
        # state.json: a cursor would rewrite that file every minute and commit a
        # change every minute. Re-reading costs nothing because the nonce list
        # already rejects a note that has been applied.
        notes = _notes(get, topic, COMMAND_MAX_AGE)
    except Exception as e:
        log.warning("could not read the mailbox: %s", e)
        return False

    seen = list(state.get("command_nonces") or [])
    entries = products.load(products_path)
    changed = False

    for note in notes:
        message = note.get("message") if isinstance(note, dict) else None
        if not message:
            continue
        try:
            payload = json.loads(message)
            cmd, sig = payload["cmd"], payload["sig"]
        except (ValueError, KeyError, TypeError):
            continue  # not one of ours; a public topic collects noise

        nonce = str(cmd.get("nonce") or "")
        if cmd.get("v") != COMMAND_VERSION or not nonce:
            continue
        if not verify(passphrase, cmd, sig):
            log.warning("ignoring a note with a bad signature")
            continue
        try:
            age = abs(time.time() - float(cmd.get("ts", 0)))
        except (TypeError, ValueError):
            continue
        if age > COMMAND_MAX_AGE:
            log.warning("ignoring a note %d seconds old", age)
            continue
        if nonce in seen:
            continue  # already applied; a repeat delivery is not a second command

        seen.append(nonce)
        action = cmd.get("action")
        try:
            if action == "add":
                entries = products.add(entries, str(cmd.get("product") or ""),
                                       str(cmd.get("label") or ""), now)
            elif action == "remove":
                entries = products.remove(entries, str(cmd.get("product") or ""))
            else:
                _reply(post, topic, nonce, False, f"unknown action {action!r}")
                continue
        except products.ProductError as e:
            log.info("command refused: %s", e)
            _reply(post, topic, nonce, False, str(e))
            continue

        changed = True
        count = len(entries)
        noun = "product" if count == 1 else "products"
        log.info("command applied: %s %s", action, cmd.get("product"))
        _reply(post, topic, nonce, True,
               f"{action}: {products.extract_asin(str(cmd.get('product')))} "
               f"({count} {noun} watched)")

    state["command_nonces"] = seen[-NONCE_MEMORY:]
    if changed:
        products.save(products_path, entries)
    return changed
