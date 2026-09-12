"""The list of watched products, and the labels and tags derived from it.

products.json is the source of truth for what the watcher polls. It is written
only in response to an explicit request to change the list, by watch/manage.py or
by a verified command from the status page; a poll never writes it, so a label a
user typed is never overwritten by a page title.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import Path

from watch import config
from watch.jsonio import read_json, write_json

ASIN_RE = re.compile(r"(?:/dp/|/gp/product/)([A-Za-z0-9]{10})(?![A-Za-z0-9])")
BARE_ASIN_RE = re.compile(r"^[A-Za-z0-9]{10}$")
SLUG_SPLIT_RE = re.compile(r"[^a-z0-9]+")

DEFAULT_LABEL_CHARS = 60  # a page title is truncated to this for display
SLUG_CHARS = 30           # maximum length of an ntfy tag slug


class ProductError(Exception):
    """Raised when a product cannot be identified, added or removed."""


def extract_asin(text: str) -> str:
    """The ASIN in a bare ASIN or an Amazon URL, uppercased."""
    value = (text or "").strip()
    m = ASIN_RE.search(value)
    if m:
        return m.group(1).upper()
    if BARE_ASIN_RE.match(value):
        return value.upper()
    raise ProductError(f"no ASIN found in {text!r}")


def load(path: str | Path) -> list[dict]:
    """The watched products.

    A missing or unreadable file falls back to the default product so a fresh
    checkout still watches something; the file itself is left alone. A file that
    holds an empty list means exactly that: watch nothing.
    """
    data = read_json(path, None, "products")
    entries = data.get("products") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return [{"asin": config.DEFAULT_ASIN, "label": "", "added": ""}]
    out = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        try:
            asin = extract_asin(str(e.get("asin", "")))
        except ProductError:
            continue
        out.append({
            "asin": asin,
            "label": str(e.get("label") or ""),
            "added": str(e.get("added") or ""),
        })
    return out


def save(path: str | Path, entries: list[dict]) -> None:
    write_json(path, {"products": entries})


def add(entries: list[dict], asin: str, label: str, when: datetime) -> list[dict]:
    """A new list with `asin` appended. Raises if it is already watched."""
    asin = extract_asin(asin)
    existing = next((e for e in entries if e["asin"] == asin), None)
    if existing is not None:
        # Naming it matters: on Amazon each colour and size is its own ASIN, so a
        # link copied before picking the variant carries the one already watched,
        # and "already being watched" on its own reads as a bug rather than that.
        name = (existing.get("label") or "").strip()
        raise ProductError(
            f"{asin} is already being watched" + (f' as "{name}"' if name else "")
        )
    return list(entries) + [
        {"asin": asin, "label": (label or "").strip(), "added": when.isoformat()}
    ]


def remove(entries: list[dict], asin: str) -> list[dict]:
    """A new list without `asin`. Raises if it is not watched."""
    asin = extract_asin(asin)
    out = [e for e in entries if e["asin"] != asin]
    if len(out) == len(entries):
        raise ProductError(f"{asin} is not being watched")
    return out


def display_label(entry: dict, title: str) -> str:
    """What to call this product: the user's label, else its page title, else the ASIN."""
    label = (entry.get("label") or "").strip()
    if label:
        return label
    title = (title or "").strip()
    if not title:
        return entry.get("asin", "")
    if len(title) > DEFAULT_LABEL_CHARS:
        return title[:DEFAULT_LABEL_CHARS] + "…"
    return title


def slug(label: str, asin: str) -> str:
    """An ntfy tag for one product: ASCII, lowercase, safe in an HTTP header.

    ntfy tags travel in the Tags header, which must be Latin-1, and a label may
    hold Hebrew or typographic characters. Accents fold to their base letters and
    everything else is dropped; a label left with nothing falls back to the ASIN.
    """
    folded = unicodedata.normalize("NFKD", label or "").encode("ascii", "ignore").decode("ascii")
    out = SLUG_SPLIT_RE.sub("-", folded.lower()).strip("-")[:SLUG_CHARS].strip("-")
    return out or (asin or "").lower()
