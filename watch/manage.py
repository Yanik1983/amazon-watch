"""Add or remove a watched product. Run by the manage workflow, never by the poll.

    python -m watch.manage --action add --product <asin or Amazon URL> [--label "Name"]
    python -m watch.manage --action remove --product <asin or Amazon URL>

Exits 1 and leaves products.json untouched when the product cannot be identified,
is already watched, or is not watched, so the workflow fails visibly and commits
nothing.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from watch import config, products


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="watch.manage")
    ap.add_argument("--action", choices=["add", "remove"], required=True)
    ap.add_argument("--product", required=True, help="ASIN or Amazon product URL")
    ap.add_argument("--label", default="", help="optional display name")
    ap.add_argument("--path", default=config.PRODUCTS_PATH)
    args = ap.parse_args(argv)

    entries = products.load(args.path)
    try:
        asin = products.extract_asin(args.product)
        if args.action == "add":
            entries = products.add(entries, asin, args.label, datetime.now(timezone.utc))
        else:
            entries = products.remove(entries, asin)
    except products.ProductError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    products.save(args.path, entries)
    print(f"{args.action}: {asin} ({len(entries)} product(s) watched)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
