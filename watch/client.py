"""Fetch an Amazon product page with the ship-to country set to Israel.

Plain HTTP clients get a captcha page from Amazon. curl_cffi impersonating Chrome
gets the real page. The ship-to country is changed without login by POSTing to
the "glow" address-change endpoint with the page's anti-CSRF token.
"""
from __future__ import annotations

import logging
import re

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


class FetchError(Exception):
    """Raised when the product page could not be fetched in the Israel context."""


def new_session():
    """A curl_cffi session that presents Chrome's TLS and header fingerprint."""
    from curl_cffi import requests  # imported lazily so tests never need it

    s = requests.Session(impersonate="chrome")
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


def fetch_product(asin: str = config.ASIN, session=None, country: str = config.COUNTRY) -> str:
    """Return the product page HTML rendered for a shopper in `country`."""
    s = session or new_session()
    url = f"{config.BASE_URL}/dp/{asin}"

    first = _check_page(s.get(url, timeout=TIMEOUT), "first GET")
    m = TOKEN_RE.search(first)
    if not m:
        raise FetchError("token: anti-csrftoken-a2z not found in page")
    token = m.group(1)

    resp = s.post(
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
            "anti-csrftoken-a2z": token,
            "Referer": url,
            "X-Requested-With": "XMLHttpRequest",
        },
        timeout=TIMEOUT,
    )
    if resp.status_code != 200:
        raise FetchError(f"address-change: HTTP {resp.status_code}")
    if not ADDRESS_UPDATED_RE.search(resp.text):
        raise FetchError(f"address-change: not updated: {resp.text[:200]}")

    second = _check_page(s.get(url, timeout=TIMEOUT), "second GET")
    g = GLOW_RE.search(second)
    if not g or "israel" not in g.group(1).lower():
        found = g.group(1).strip() if g else "(no glow line)"
        raise FetchError(f"glow: ship-to country is not Israel: {found}")
    log.info("fetched %s in Israel context (%d characters)", asin, len(second))
    return second
