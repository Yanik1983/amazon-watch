"""Fetch an Amazon product page with the ship-to country set to Israel.

Plain HTTP clients get a captcha page from Amazon. curl_cffi impersonating Chrome
gets the real page. The ship-to country is changed without login by POSTing to
the "glow" address-change endpoint with the page's anti-CSRF token.
"""
from __future__ import annotations

import logging
import re
import time

from watch import config

log = logging.getLogger(__name__)

TOKEN_RE = re.compile(
    r'anti-csrftoken-a2z(?:"|&quot;)\s*(?::|value=)\s*(?:"|&quot;)([^"&]+)'
)
GLOW_RE = re.compile(r'id="glow-ingress-line2"[^>]*>\s*([^<]*)<', re.S)
# The flag is a boolean 0/1; the trailing guard stops a value such as 10 matching.
ADDRESS_UPDATED_RE = re.compile(r'"isAddressUpdated"\s*:\s*1(?!\d)')

# A real product page is around 2.7 million characters; a captcha page is under 4,000.
MIN_PAGE_CHARS = 20_000
CAPTCHA_SCAN_CHARS = 5_000
TIMEOUT = 30  # seconds allowed for each request to Amazon

# A captcha on the handshake is often a verdict on this one connection rather
# than on the runner's address, so the handshake is retried on a fresh session
# that presents a different browser. Each entry is a curl_cffi impersonation
# target ("chrome" resolves to the newest Chrome the library knows). Only
# these three got a real page in a probe on 2026-09-14: Safari, Firefox and
# several older Chrome targets were served a captcha even from a home address.
HANDSHAKE_PROFILES = ("chrome", "chrome124", "edge101")
# Seconds to wait before the second and third attempts.
HANDSHAKE_BACKOFF = (5, 20)


class FetchError(Exception):
    """Raised when the product page could not be fetched in the Israel context."""


def new_session(profile: str = HANDSHAKE_PROFILES[0]):
    """A curl_cffi session presenting the TLS and header fingerprint of `profile`."""
    from curl_cffi import requests  # imported lazily so tests never need it

    s = requests.Session(impersonate=profile)
    s.headers.update({"Accept-Language": "en-US,en;q=0.9"})
    return s


def _check_page(resp, step: str) -> str:
    if resp.status_code != 200:
        raise FetchError(f"{step}: HTTP {resp.status_code}")
    text = resp.text
    if "captcha" in text[:CAPTCHA_SCAN_CHARS].lower():
        raise FetchError(f"{step}: captcha page returned")
    if len(text) < MIN_PAGE_CHARS:
        raise FetchError(f"{step}: body too small ({len(text)} characters)")
    return text


def set_israel(session, asin: str = config.DEFAULT_ASIN,
               country: str = config.COUNTRY) -> None:
    """Put this session's ship-to country into `country`.

    One handshake serves a whole poll cycle: Amazon keeps the choice in the
    session's cookies, so every later page fetched on the same session is already
    rendered for that country. Verification is left to fetch_page, which checks
    the glow line on every page it returns.
    """
    url = config.product_url(asin)
    first = _check_page(session.get(url, timeout=TIMEOUT), "first GET")
    m = TOKEN_RE.search(first)
    if not m:
        raise FetchError("token: anti-csrftoken-a2z not found in page")

    resp = session.post(
        config.ADDRESS_CHANGE_URL,
        data={
            "locationType": "COUNTRY",
            "countryCode": country,
            "deviceType": "web",
            "storeContext": "generic",
            "pageType": "Detail",
            "actionSource": "glow",
        },
        headers={
            "anti-csrftoken-a2z": m.group(1),
            "Referer": url,
            "X-Requested-With": "XMLHttpRequest",
        },
        timeout=TIMEOUT,
    )
    if resp.status_code != 200:
        raise FetchError(f"address-change: HTTP {resp.status_code}")
    if not ADDRESS_UPDATED_RE.search(resp.text):
        raise FetchError(f"address-change: not updated: {resp.text[:200]}")
    log.info("ship-to country set to %s", country)


def open_israel_session(session_factory=new_session, sleep=time.sleep):
    """A session with the ship-to country set, retrying the handshake if blocked.

    Every attempt starts a new session with the next browser profile, so a
    connection Amazon has already flagged is never reused. The last error is
    raised once every profile has been tried.
    """
    last: FetchError | None = None
    for i, profile in enumerate(HANDSHAKE_PROFILES):
        if i:
            sleep(HANDSHAKE_BACKOFF[i - 1])
        session = session_factory(profile)
        try:
            set_israel(session)
            return session
        except FetchError as e:
            last = e
            log.warning("handshake as %s failed (attempt %d of %d): %s",
                        profile, i + 1, len(HANDSHAKE_PROFILES), e)
    assert last is not None
    raise last


def fetch_page(session, asin: str) -> str:
    """One product page, verified to have been rendered for the Israel context."""
    html = _check_page(session.get(config.product_url(asin), timeout=TIMEOUT), f"GET {asin}")
    g = GLOW_RE.search(html)
    if not g or "israel" not in g.group(1).lower():
        found = g.group(1).strip() if g else "(no glow line)"
        raise FetchError(f"glow: ship-to country is not Israel: {found}")
    log.info("fetched %s in Israel context (%d characters)", asin, len(html))
    return html


def fetch_product(asin: str = config.DEFAULT_ASIN, session=None,
                  country: str = config.COUNTRY) -> str:
    """One product page from a fresh session.

    For one-off use. The poll calls set_israel once and then fetch_page per
    product, so it pays the handshake once rather than once per product.
    """
    s = session or new_session()
    set_israel(s, asin, country)
    return fetch_page(s, asin)
