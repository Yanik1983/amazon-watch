"""Fetch the watched product page from this machine and save a trimmed test fixture.

Usage: python scripts/capture_fixture.py [output path]
Keeps only the sections the parser reads: product title, glow ingress line,
delivery block, merchant info. The full page is about 2.7 MB; the fixture is small.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from watch.client import fetch_product

SECTIONS = [
    (r'<span id="productTitle".*?</span>', re.S, "productTitle"),
    (r'<[a-z]+[^>]*id="glow-ingress-line2".*?</[a-z]+>', re.S, "glow-ingress-line2"),
    (r'id="mir-layout-DELIVERY_BLOCK"', 0, "DELIVERY_BLOCK"),
    (r'id="merchantInfo"', 0, "merchantInfo"),
]
WINDOW = 6000  # bytes kept after an id-only anchor


def trim(html: str) -> str:
    parts = ["<html><body>"]
    for pattern, flags, label in SECTIONS:
        m = re.search(pattern, html, flags)
        if not m:
            parts.append(f"<!-- section not found: {label} -->")
            continue
        if pattern.startswith("id="):
            parts.append("<div " + html[m.start(): m.start() + WINDOW])
        else:
            parts.append(m.group(0))
    parts.append("</body></html>")
    return "\n".join(parts)


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures/not_free.html")
    html = fetch_product()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(trim(html), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    print("delivery prices:", re.findall(r'data-csa-c-delivery-price="([^"]*)"', html))
    return 0


if __name__ == "__main__":
    sys.exit(main())
