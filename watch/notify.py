"""Send push (and optional email copy) notifications through ntfy."""
from __future__ import annotations

import logging

import requests

from watch import config

log = logging.getLogger(__name__)


def send(
    title: str,
    body: str,
    click: str | None = None,
    priority: str = "high",
    tags: str = "package,tada",
    post=requests.post,
) -> bool:
    """POST a message to the configured ntfy topic. Returns True if sent."""
    if not config.NTFY_TOPIC:
        log.info("NTFY_TOPIC not set; would send: %s / %s", title, body)
        return False
    headers = {"Title": title, "Priority": priority, "Tags": tags}
    if click:
        headers["Click"] = click
    if config.NTFY_TOKEN:
        headers["Authorization"] = f"Bearer {config.NTFY_TOKEN}"
    if config.NTFY_EMAIL:
        headers["Email"] = config.NTFY_EMAIL
    url = f"{config.NTFY_SERVER}/{config.NTFY_TOPIC}"

    ok = _post(post, url, body, headers)
    if not ok and "Email" in headers:
        # ntfy.sh rejects anonymous email sending (HTTP 400). Push still matters:
        # retry once without the email copy rather than losing the alert.
        log.warning("retrying notification without email copy")
        headers = {k: v for k, v in headers.items() if k != "Email"}
        ok = _post(post, url, body, headers)
    return ok


def _post(post, url: str, body: str, headers: dict) -> bool:
    try:
        resp = post(url, data=body.encode("utf-8"), headers=headers, timeout=20)
    except Exception as e:
        log.error("ntfy send failed: %s", e)
        return False
    if getattr(resp, "status_code", 0) != 200:
        log.error("ntfy returned %s: %s", resp.status_code, getattr(resp, "text", ""))
        return False
    return True
