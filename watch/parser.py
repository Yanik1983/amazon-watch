"""Extract the free-shipping eligibility from an Amazon product page."""
from __future__ import annotations

import html as html_mod
import re
from dataclasses import dataclass

COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
DELIVERY_PRICE_RE = re.compile(r'data-csa-c-delivery-price="([^"]*)"')
DELIVERY_BLOCK_ANCHOR = 'id="mir-layout-DELIVERY_BLOCK"'
DELIVERY_BLOCK_WINDOW = 6000  # characters of HTML read after the anchor
FREE_VALUES = frozenset({"FREE", "$0.00", "0.00", "ILS 0.00"})
TITLE_ANCHOR = 'id="productTitle"'
MERCHANT_ANCHOR = 'id="merchantInfo"'
SELLER_ANCHOR = 'id="sellerProfileTriggerId"'
ELEMENT_WINDOW = 20_000  # characters searched for an element's closing tag
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

    return Product(title=title, free=free, delivery_text=delivery_text, merchant=merchant)
