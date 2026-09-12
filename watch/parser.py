"""Extract the free-shipping eligibility from an Amazon product page."""
from __future__ import annotations

import html as html_mod
import re
from dataclasses import dataclass

COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
DELIVERY_PRICE_RE = re.compile(r'data-csa-c-delivery-price="([^"]*)"')
DELIVERY_BLOCK_ANCHOR = 'id="mir-layout-DELIVERY_BLOCK"'
DELIVERY_BLOCK_WINDOW = 6000  # bytes of HTML read after the anchor for text fallbacks
FREE_VALUES = frozenset({"FREE", "$0.00", "0.00", "ILS 0.00"})
TITLE_RE = re.compile(r'id="productTitle"[^>]*>(.*?)</span>', re.S)
MERCHANT_RE = re.compile(r'id="merchantInfo"[^>]*>(.*?)</div>', re.S)
SELLER_RE = re.compile(r'id="sellerProfileTriggerId"[^>]*>(.*?)</a>', re.S)
TAG_RE = re.compile(r"<[^>]+>")


class ParseError(Exception):
    """Raised when the page does not contain a recognisable delivery block."""


@dataclass(frozen=True)
class Product:
    title: str
    free: bool
    delivery_text: str
    merchant: str


def _text(fragment: str) -> str:
    """Strip tags, unescape entities, collapse whitespace."""
    return " ".join(html_mod.unescape(TAG_RE.sub(" ", fragment)).split())


def parse(html: str) -> Product:
    html = COMMENT_RE.sub("", html)
    anchor = html.find(DELIVERY_BLOCK_ANCHOR)
    if anchor >= 0:
        search_text = html[anchor: anchor + DELIVERY_BLOCK_WINDOW]
    else:
        search_text = html

    delivery_text = ""
    free = None
    for m in DELIVERY_PRICE_RE.finditer(search_text):
        value = html_mod.unescape(m.group(1)).replace("\xa0", " ").strip()
        if value.lower() == "fastest":
            continue
        delivery_text = value
        free = value.upper() in FREE_VALUES
        break

    if free is None:
        if anchor < 0:
            raise ParseError("no delivery block found on page")
        delivery_text = ""
        block = _text(search_text)
        free = "free international delivery" in block.lower()

    t = TITLE_RE.search(html)
    title = _text(t.group(1)) if t else ""

    m = MERCHANT_RE.search(html) or SELLER_RE.search(html)
    merchant = _text(m.group(1)) if m else ""

    return Product(title=title, free=free, delivery_text=delivery_text, merchant=merchant)
