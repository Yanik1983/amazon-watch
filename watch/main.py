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

    try:
        product: Product = parse(fetch(config.ASIN))
    except (FetchError, ParseError) as e:
        st["fail_count"] = int(st.get("fail_count", 0)) + 1
        st["last_error"] = str(e)
        log.error("poll failed (%d in a row): %s", st["fail_count"], e)
        fail_count = st["fail_count"]
        should_warn = fail_count == config.FAIL_ALERT_AT or (
            fail_count > config.FAIL_ALERT_AT
            and (fail_count - config.FAIL_ALERT_AT) % config.FAIL_REWARN_EVERY == 0
        )
        if should_warn:
            notifier(
                "Amazon watcher failing",
                f"{st['fail_count']} consecutive polls failed. Last error: {e}",
                priority="default",
                tags="warning",
            )
        return _finish(st, history, False, state_path, history_path, page_path, now)

    st["fail_count"] = 0
    st["last_error"] = None
    st["last_success"] = now.isoformat()
    previous = st.get("product") or None
    prev_free = previous.get("free") if previous else None

    history_changed = False
    if prev_free is None:
        history_mod.append_flip(history, now, product.free, product.delivery_text)
        history_changed = True
        log.info("first observation: free=%s (%s)", product.free, product.delivery_text)
    elif product.free != prev_free:
        history_mod.append_flip(history, now, product.free, product.delivery_text)
        history_changed = True
        if product.free:
            notifier(
                "Amazon: free shipping to Israel!",
                f"{product.title}\n{product.delivery_text}",
                click=config.PRODUCT_URL,
                priority="high",
            )
            log.info("notified: became free")
        else:
            log.info("became paid again (%s); no push", product.delivery_text)
    else:
        log.info("unchanged: free=%s (%s)", product.free, product.delivery_text)

    st["product"] = {**asdict(product), "checked_at": now.isoformat()}
    return _finish(st, history, history_changed, state_path, history_path, page_path, now)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    try:
        st = run()
        log.info("done: fail_count=%s free=%s", st["fail_count"], (st.get("product") or {}).get("free"))
    except Exception:  # never fail the workflow; page/state may still be committed
        log.exception("unexpected error in poll")
    return 0


if __name__ == "__main__":
    sys.exit(main())
