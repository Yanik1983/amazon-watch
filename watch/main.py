"""One poll cycle: fetch every watched product, notify on flips, persist, render."""
from __future__ import annotations

import logging
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from watch import config, history as history_mod, notify
from watch import products as products_mod, state as state_mod
from watch.client import FetchError, fetch_page, new_session, set_israel
from watch.parser import ParseError, Product, parse
from watch.render import render_page

log = logging.getLogger("watch")

Fetch = Callable[[str], str]
Notifier = Callable[..., bool]


def _session_fetch() -> Fetch:
    """A fetcher sharing one Israel-context session across the whole cycle.

    The handshake costs two requests and every product after that costs one, so
    watching ten products is twelve requests an hour rather than thirty.
    """
    session = new_session()
    set_israel(session)
    return lambda asin: fetch_page(session, asin)


def _warning_due(fail_count: int) -> bool:
    """True on the poll where a warning is owed for this failure streak.

    Once at FAIL_ALERT_AT, then every FAIL_REWARN_EVERY polls while it lasts, so
    a watcher that quietly breaks keeps saying so instead of going silent.
    """
    if fail_count < config.FAIL_ALERT_AT:
        return False
    return (fail_count - config.FAIL_ALERT_AT) % config.FAIL_REWARN_EVERY == 0


def run(
    fetch: Fetch | None = None,
    notifier: Notifier = notify.send,
    products_path: str | Path = config.PRODUCTS_PATH,
    state_path: str | Path = config.STATE_PATH,
    history_path: str | Path = config.HISTORY_PATH,
    page_path: str | Path = config.PAGE_PATH,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    entries = products_mod.load(products_path)
    st = state_mod.load(state_path)
    history = history_mod.load(history_path)
    st["last_checked"] = now.isoformat()

    setup_error: FetchError | None = None
    if fetch is None and entries:
        try:
            fetch = _session_fetch()
        except FetchError as e:
            # The handshake failed, so no product can be read this cycle. Each one
            # records the failure and the combined rule below decides the alert.
            setup_error = e
            log.error("could not set the Israel context: %s", e)

    history_changed = False
    due: list[tuple[dict, dict]] = []   # (product entry, state entry) owed a warning
    failed = 0

    for entry_def in entries:
        asin = entry_def["asin"]
        ps = state_mod.entry(st, asin)
        try:
            if setup_error is not None:
                raise setup_error
            product: Product = parse(fetch(asin))
        except (FetchError, ParseError) as e:
            failed += 1
            ps["fail_count"] = int(ps.get("fail_count") or 0) + 1
            ps["last_error"] = str(e)
            log.error("%s failed (%d in a row): %s", asin, ps["fail_count"], e)
            if _warning_due(ps["fail_count"]):
                due.append((entry_def, ps))
            continue

        prev_free = ps.get("free")
        ps["fail_count"] = 0
        ps["last_error"] = None
        ps["last_success"] = now.isoformat()
        ps.update(asdict(product))
        ps["checked_at"] = now.isoformat()

        announce = False
        if prev_free is None:
            # Nothing recorded before: the first poll of this product, or a lost
            # state file. Free right now is news either way, so it is announced.
            history_mod.append_flip(history, now, asin, product.free, product.delivery_text)
            history_changed = True
            announce = product.free
            log.info("%s first seen: free=%s (%s)", asin, product.free, product.delivery_text)
        elif product.free != prev_free:
            history_mod.append_flip(history, now, asin, product.free, product.delivery_text)
            history_changed = True
            announce = product.free
            if not product.free:
                log.info("%s became paid again (%s); no push", asin, product.delivery_text)
        else:
            log.info("%s unchanged: free=%s (%s)", asin, product.free, product.delivery_text)

        if announce:
            label = products_mod.display_label(entry_def, product.title)
            notifier(
                f"FREE: {label}",
                f"{product.title}\n{product.delivery_text}",
                click=config.product_url(asin),
                priority="high",
                tags=f"package,{products_mod.slug(label, asin)}",
            )
            log.info("%s notified: free shipping available", asin)

    if due and failed == len(entries):
        # Everything failed at once, which is a captcha or a network problem
        # rather than a product problem: one alert, not one per product.
        count = len(entries)
        noun = "product" if count == 1 else "products"
        notifier(
            "Amazon watcher failing",
            f"All {count} watched {noun} failed to poll. Last error: {due[-1][1]['last_error']}",
            priority="default",
            tags="warning",
        )
    else:
        for entry_def, ps in due:
            label = products_mod.display_label(entry_def, ps.get("title") or "")
            notifier(
                f"Amazon watcher failing: {label}",
                f"{ps['fail_count']} consecutive polls failed. Last error: {ps['last_error']}",
                priority="default",
                tags=f"warning,{products_mod.slug(label, entry_def['asin'])}",
            )

    state_mod.prune(st, [e["asin"] for e in entries])
    state_mod.save(state_path, st)
    if history_changed:
        history_mod.save(history_path, history)
    page = Path(page_path)
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(render_page(st, history, entries, now), encoding="utf-8")
    return st


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    try:
        st = run()
        free = [a for a, e in st["products"].items() if e.get("free")]
        log.info("done: %d watched, free: %s", len(st["products"]), free or "none")
    except Exception:  # never fail the workflow; page and state may still be committed
        log.exception("unexpected error in poll")
    return 0


if __name__ == "__main__":
    sys.exit(main())
