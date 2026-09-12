"""Extract the free-shipping eligibility from an Amazon product page."""
from __future__ import annotations

import html as html_mod
import re
from dataclasses import dataclass

DELIVERY_PRICE_RE = re.compile(r'data-csa-c-delivery-price="([^"]*)"')
DELIVERY_BLOCK_ANCHOR = 'id="mir-layout-DELIVERY_BLOCK"'
DELIVERY_BLOCK_WINDOW = 6000  # bytes of HTML read after the anchor for text fallbacks
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
    price = DELIVERY_PRICE_RE.search(html)
    anchor = html.find(DELIVERY_BLOCK_ANCHOR)
    if price is None and anchor < 0:
        raise ParseError("no delivery block found on page")

    if price is not None:
        delivery_text = html_mod.unescape(price.group(1)).replace("\xa0", " ").strip()
        free = delivery_text.upper() == "FREE"
    else:
        delivery_text = ""
        block = _text(html[anchor: anchor + DELIVERY_BLOCK_WINDOW])
        free = "free international delivery" in block.lower()

    t = TITLE_RE.search(html)
    title = _text(t.group(1)) if t else ""

    m = MERCHANT_RE.search(html) or SELLER_RE.search(html)
    merchant = _text(m.group(1)) if m else ""

    return Product(title=title, free=free, delivery_text=delivery_text, merchant=merchant)
