"""Persist watcher state between polls as JSON, one entry per watched product."""
from __future__ import annotations

from pathlib import Path

from watch import config
from watch.jsonio import read_json, write_json

VERSION = 2


def default_state() -> dict:
    return {
        "version": VERSION,
        "last_checked": None,       # ISO datetime (UTC) of the last poll cycle
        "products": {},             # ASIN -> entry
        "command_nonces": [],   # nonces of applied page commands, newest last
    }


def default_entry() -> dict:
    return {
        "free": None,           # None until the product has been seen at least once
        "title": "",
        "delivery_text": "",
        "merchant": "",
        "checked_at": None,     # ISO datetime (UTC) of the last successful parse
        "last_success": None,   # same, kept separate so the page can say "last good"
        "fail_count": 0,        # consecutive failed polls for this product
        "last_error": None,     # message of the most recent failure, cleared on success
    }


def _migrate_v1(data: dict) -> dict:
    """Fold a single-product state file into the per-product shape.

    Version 1 had one product at the top level with the failure fields beside it.
    Those belong to the default ASIN, which is the only product that file could
    have described.
    """
    st = default_state()
    st["last_checked"] = data.get("last_checked")
    product = data.get("product")
    if not isinstance(product, dict):
        return st
    e = default_entry()
    for key in ("free", "title", "delivery_text", "merchant", "checked_at"):
        if key in product:
            e[key] = product[key]
    e["fail_count"] = int(data.get("fail_count") or 0)
    e["last_error"] = data.get("last_error")
    e["last_success"] = data.get("last_success")
    st["products"][config.DEFAULT_ASIN] = e
    return st


def load(path: str | Path) -> dict:
    data = read_json(path, None, "state")
    if not isinstance(data, dict):
        return default_state()
    if data.get("version") != VERSION:
        return _migrate_v1(data)
    st = default_state()
    st["last_checked"] = data.get("last_checked")
    nonces = data.get("command_nonces")
    if isinstance(nonces, list):
        st["command_nonces"] = [str(n) for n in nonces]
    for asin, raw in (data.get("products") or {}).items():
        e = default_entry()
        if isinstance(raw, dict):
            e.update(raw)
        st["products"][asin] = e
    return st


def save(path: str | Path, state: dict) -> None:
    write_json(path, state, sort_keys=True)


def entry(state: dict, asin: str) -> dict:
    """The live entry for `asin`, inserting a fresh one when it is not there yet."""
    return state.setdefault("products", {}).setdefault(asin, default_entry())


def prune(state: dict, keep_asins) -> None:
    """Drop entries for products no longer watched, so removing one cleans up."""
    keep = set(keep_asins)
    state["products"] = {a: e for a, e in (state.get("products") or {}).items() if a in keep}
