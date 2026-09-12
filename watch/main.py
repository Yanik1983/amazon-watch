"""Temporary poll entry point: fetch the page and log what the delivery block says.

Replaced by the full poll cycle once the parser and persistence modules exist.
"""
from __future__ import annotations

import logging
import re
import sys

from watch.client import FetchError, fetch_product

log = logging.getLogger("watch")


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    try:
        html = fetch_product()
        prices = re.findall(r'data-csa-c-delivery-price="([^"]*)"', html)
        log.info("delivery prices on page: %s", prices)
    except FetchError as e:
        log.error("fetch failed: %s", e)
    except Exception:  # never fail the workflow
        log.exception("unexpected error")
    return 0


if __name__ == "__main__":
    sys.exit(main())
