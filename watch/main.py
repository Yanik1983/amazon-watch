"""One poll cycle: fetch every watched product, notify on flips, persist, render."""
from __future__ import annotations

import logging
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from watch import commands, config, history as history_mod, notify
from watch import products as products_mod, state as state_mod
from watch.client import FetchError, fetch_page, open_israel_session
from watch.parser import ParseError, Product, parse
from watch.render import render_page

log = logging.getLogger("watch")

Fetch = Callable[[str], str]
Notifier = Callable[..., bool]

# Exit status of `python -m watch.tick` asking the workflow to end this job and
# start another. A new job runs on a new machine with a new address, which is
# the one thing that helps once Amazon has decided to captcha this one.
EXIT_RESTART = 3


def _session_fetch() -> Fetch:
    """A fetcher sharing one Israel-context session across the whole cycle.

    The handshake costs two requests and every product after that costs one, so
    watching ten products is twelve requests an hour rather than thirty.
    """
    session = open_israel_session()

    def fetch(asin: str) -> str:
        nonlocal session
        try:
            return fetch_page(session, asin)
        except FetchError as e:
            if "captcha" not in str(e):
                raise
            # The handshake passed and this page was still a captcha: the
            # verdict is on the connection, not the product. One fresh session
            # (with its own handshake retries) before the product counts as failed.
            log.warning("%s: captcha after a good handshake; reopening the session", asin)
            session = open_israel_session()
            return fetch_page(session, asin)
    return fetch


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
    _write_page(page_path, st, history, entries, now)
    return st


def _write_page(page_path: str | Path, st: dict, history: list[dict],
                entries: list[dict], now: datetime) -> None:
    page = Path(page_path)
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(render_page(st, history, entries, now), encoding="utf-8")


def poll_due(st: dict, now: datetime) -> bool:
    """Whether enough time has passed since the last Amazon poll.

    Read from the state file rather than counted in the job, so the hourly cadence
    survives a job being cancelled and restarted, which happens on every push.
    """
    last = st.get("last_checked")
    if not last:
        return True
    try:
        when = datetime.fromisoformat(last)
    except (ValueError, TypeError):
        return True
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)

    interval = config.POLL_INTERVAL_SECONDS
    entries = st.get("products") or {}
    if entries and all(int(e.get("fail_count") or 0) > 0 for e in entries.values()):
        # Nothing got through last time, which is a transient block far more often
        # than it is anything else. Come back sooner rather than showing an hour
        # of stale data. Only ever shortens the wait, and only while everything
        # is failing, so a working watcher still asks Amazon once an hour.
        interval = min(interval, config.RETRY_INTERVAL_SECONDS)
    return (now - when).total_seconds() >= interval


def restart_wanted(st: dict, now: datetime) -> bool:
    """Whether this tick's poll showed Amazon blocking the whole job.

    True only on a tick that polled (last_checked is this tick) and saw every
    product fail for at least RESTART_AFTER_FAILS polls in a row. Tying it to a
    poll bounds restarts to one per retry interval, even when every address
    GitHub hands out is blocked.
    """
    if st.get("last_checked") != now.isoformat():
        return False
    entries = st.get("products") or {}
    if not entries:
        return False
    return all(int(e.get("fail_count") or 0) >= config.RESTART_AFTER_FAILS
               for e in entries.values())


def tick(
    passphrase: str | None = None,
    products_path: str | Path = config.PRODUCTS_PATH,
    state_path: str | Path = config.STATE_PATH,
    now: datetime | None = None,
    get=None,
    post=None,
    **run_kwargs,
) -> dict:
    """One minute of the watcher's life: read the mailbox, and poll if it is time.

    Splitting the mailbox check from the Amazon poll is the whole point: commands
    from the status page are picked up within a minute while Amazon keeps being
    asked once an hour.
    """
    now = now or datetime.now(timezone.utc)
    st = state_mod.load(state_path)
    kw = {k: v for k, v in {"get": get, "post": post}.items() if v is not None}
    changed = commands.apply_commands(
        config.CMD_PASSPHRASE if passphrase is None else passphrase,
        products_path, st, now, **kw,
    )
    if changed:
        # Persist the applied nonces before polling, so a poll that dies partway
        # cannot cause the same command to be applied a second time.
        state_mod.save(state_path, st)
    if changed or poll_due(st, now):
        return run(products_path=products_path, state_path=state_path, now=now, **run_kwargs)

    # No Amazon poll this tick, but still re-render: the page is a pure function of
    # the stored data, so this is free when nothing changed and picks up a new page
    # layout within a minute of it being deployed.
    log.info("no poll due; next one after %s", st.get("last_checked"))
    _write_page(
        run_kwargs.get("page_path", config.PAGE_PATH),
        st,
        history_mod.load(run_kwargs.get("history_path", config.HISTORY_PATH)),
        products_mod.load(products_path),
        now,
    )
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


def tick_main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    now = datetime.now(timezone.utc)
    try:
        st = tick(now=now)
    except Exception:  # a bad tick must not end the loop; the next one tries again
        log.exception("unexpected error in tick")
        return 0
    if restart_wanted(st, now):
        log.warning("every product has failed %d polls in a row; asking for a new runner",
                    config.RESTART_AFTER_FAILS)
        return EXIT_RESTART
    return 0


if __name__ == "__main__":
    sys.exit(main())
