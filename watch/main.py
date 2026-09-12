"""One poll cycle: fetch the page, parse eligibility, notify on flip, persist, render."""
from __future__ import annotations

import logging
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from watch import config, history as history_mod, notify, state as state_mod
from watch.client import FetchError, fetch_product
from watch.parser import ParseError, Product, parse
from watch.render import render_page

log = logging.getLogger("watch")

Fetch = Callable[[str], str]
Notifier = Callable[..., bool]


def _finish(st: dict, history: list[dict], history_changed: bool,
            state_path, history_path, page_path, now: datetime) -> dict:
    st["last_checked"] = now.isoformat()
    state_mod.save(state_path, st)
    if history_changed:
        history_mod.save(history_path, history)
    page = render_page(st, history, now)
    p = Path(page_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(page, encoding="utf-8")
    return st


def run(
    fetch: Fetch = fetch_product,
    notifier: Notifier = notify.send,
    state_path: str | Path = config.STATE_PATH,
    history_path: str | Path = config.HISTORY_PATH,
    page_path: str | Path = config.PAGE_PATH,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    st = state_mod.load(state_path)
    history = history_mod.load(history_path)

    e_state = state_mod.entry(st, config.DEFAULT_ASIN)

    try:
        product: Product = parse(fetch(config.DEFAULT_ASIN))
    except (FetchError, ParseError) as e:
        e_state["fail_count"] = int(e_state.get("fail_count", 0)) + 1
        e_state["last_error"] = str(e)
        log.error("poll failed (%d in a row): %s", e_state["fail_count"], e)
        fail_count = e_state["fail_count"]
        should_warn = fail_count == config.FAIL_ALERT_AT or (
            fail_count > config.FAIL_ALERT_AT
            and (fail_count - config.FAIL_ALERT_AT) % config.FAIL_REWARN_EVERY == 0
        )
        if should_warn:
            notifier(
                "Amazon watcher failing",
                f"{e_state['fail_count']} consecutive polls failed. Last error: {e}",
                priority="default",
                tags="warning",
            )
        return _finish(st, history, False, state_path, history_path, page_path, now)

    prev_free = e_state.get("free")
    e_state["fail_count"] = 0
    e_state["last_error"] = None
    e_state["last_success"] = now.isoformat()

    history_changed = False
    announce = False
    if prev_free is None:
        # Nothing recorded before: either the first ever poll, or state.json was lost.
        # Free right now is news in both cases, so it is announced.
        history_mod.append_flip(history, now, config.DEFAULT_ASIN, product.free, product.delivery_text)
        history_changed = True
        announce = product.free
        log.info("first observation: free=%s (%s)", product.free, product.delivery_text)
    elif product.free != prev_free:
        history_mod.append_flip(history, now, config.DEFAULT_ASIN, product.free, product.delivery_text)
        history_changed = True
        announce = product.free
        if not product.free:
            log.info("became paid again (%s); no push", product.delivery_text)
    else:
        log.info("unchanged: free=%s (%s)", product.free, product.delivery_text)

    if announce:
        notifier(
            "Amazon: free shipping to Israel!",
            f"{product.title}\n{product.delivery_text}",
            click=config.product_url(config.DEFAULT_ASIN),
            priority="high",
        )
        log.info("notified: free shipping available")

    e_state.update(asdict(product))
    e_state["checked_at"] = now.isoformat()
    return _finish(st, history, history_changed, state_path, history_path, page_path, now)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    try:
        st = run()
        e = st["products"].get(config.DEFAULT_ASIN) or {}
        log.info("done: fail_count=%s free=%s", e.get("fail_count"), e.get("free"))
    except Exception:  # never fail the workflow; page/state may still be committed
        log.exception("unexpected error in poll")
    return 0


if __name__ == "__main__":
    sys.exit(main())
