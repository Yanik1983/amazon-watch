"""Extract the free-shipping eligibility from an Amazon product page."""
from __future__ import annotations

import html as html_mod
import re
from dataclasses import dataclass, field

COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
DELIVERY_PRICE_RE = re.compile(r'data-csa-c-delivery-price="([^"]*)"')
DELIVERY_BLOCK_ANCHOR = 'id="mir-layout-DELIVERY_BLOCK"'
DELIVERY_BLOCK_WINDOW = 6000  # characters of HTML read after the anchor
FREE_VALUES = frozenset({"FREE", "$0.00", "0.00", "ILS 0.00"})
TITLE_ANCHOR = 'id="productTitle"'
MERCHANT_ANCHOR = 'id="merchantInfo"'
SELLER_ANCHOR = 'id="sellerProfileTriggerId"'
ELEMENT_WINDOW = 20_000  # characters searched for an element's closing tag
PRICE_ANCHORS = (
    'id="corePrice_feature_div"',
    'id="corePriceDisplay_desktop_feature_div"',
    'id="apex_desktop"',
)
OFFSCREEN_RE = re.compile(r'<span class="a-offscreen">(.*?)</span>', re.S)
LIST_PRICE_RE = re.compile(
    r'class="[^"]*a-text-price[^"]*"[^>]*>\s*<span class="a-offscreen">(.*?)</span>', re.S
)
PRICE_WINDOW = 4000
BULLETS_ANCHOR = 'id="feature-bullets"'
BULLETS_WINDOW = 8000
BULLET_RE = re.compile(r"<li\b[^>]*>(.*?)</li>", re.S | re.I)
DESCRIPTION_ANCHOR = 'id="productDescription"'
MAX_BULLETS = 12
TAG_RE = re.compile(r"<[^>]+>")


class ParseError(Exception):
    """Raised when the page does not contain a recognisable delivery block."""


@dataclass(frozen=True)
class Product:
    title: str
    free: bool
    delivery_text: str
    merchant: str
    price: str = ""
    list_price: str = ""
    description: list[str] = field(default_factory=list)


def _text(fragment: str) -> str:
    """Strip tags, unescape entities, collapse whitespace."""
    return " ".join(html_mod.unescape(TAG_RE.sub(" ", fragment)).split())


def _element_text(html: str, anchor: str, tag: str) -> str:
    """Text of the element whose opening tag carries `anchor`, nesting included.

    Amazon nests spans inside #productTitle and divs inside #merchantInfo, so
    stopping at the first closing tag would truncate the value. The search for the
    matching close is capped at ELEMENT_WINDOW characters; an element that never
    closes within that window yields an empty string rather than the rest of the page.
    """
    i = html.find(anchor)
    if i < 0:
        return ""
    start = html.find(">", i)
    if start < 0:
        return ""
    window = html[start + 1: start + 1 + ELEMENT_WINDOW]
    open_re = re.compile(rf"<{tag}\b", re.I)
    close_re = re.compile(rf"</{tag}\s*>", re.I)
    depth = 1
    pos = 0
    while True:
        nxt_close = close_re.search(window, pos)
        if not nxt_close:
            return ""
        nxt_open = open_re.search(window, pos)
        if nxt_open and nxt_open.start() < nxt_close.start():
            depth += 1
            pos = nxt_open.end()
            continue
        depth -= 1
        if depth == 0:
            return _text(window[: nxt_close.start()])
        pos = nxt_close.end()


def _prices(html: str) -> list[str]:
    """Current price and, when struck through, the list price ("" when absent)."""
    for anchor in PRICE_ANCHORS:
        i = html.find(anchor)
        if i < 0:
            continue
        block = html[i: i + PRICE_WINDOW]
        listed = LIST_PRICE_RE.search(block)
        list_price = _text(listed.group(1)) if listed else ""
        for m in OFFSCREEN_RE.finditer(block):
            value = _text(m.group(1))
            if value and value != list_price:
                return value, list_price
        if listed:
            return "", list_price
    return "", ""


def _description(html: str) -> list[str]:
    """Feature bullets, or the plain product description when there are none."""
    i = html.find(BULLETS_ANCHOR)
    if i >= 0:
        items = [_text(m.group(1)) for m in BULLET_RE.finditer(html[i: i + BULLETS_WINDOW])]
        items = [t for t in items if t and "make sure this fits" not in t.lower()]
        if items:
            return items[:MAX_BULLETS]
    text = _element_text(html, DESCRIPTION_ANCHOR, "div")
    return [text] if text else []


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

    title = _element_text(html, TITLE_ANCHOR, "span")
    merchant = _element_text(html, MERCHANT_ANCHOR, "div") or _element_text(
        html, SELLER_ANCHOR, "a"
    )

    price, list_price = _prices(html)
    return Product(
        title=title,
        free=free,
        delivery_text=delivery_text,
        merchant=merchant,
        price=price,
        list_price=list_price,
        description=_description(html),
    )
