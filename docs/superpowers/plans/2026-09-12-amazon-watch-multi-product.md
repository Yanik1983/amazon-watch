# Amazon watcher multiple products: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Watch any number of Amazon products instead of one, add and remove them from a phone through a GitHub Actions workflow, and tag every notification with the product it belongs to.

**Architecture:** A committed `products.json` becomes the source of truth for what is watched. State and history gain an ASIN dimension and migrate their version 1 files silently on first read. The poll sets the ship-to Israel context once per cycle and reuses the session for every product. The status page renders one card per product and links to a `manage` workflow that edits `products.json`.

**Tech Stack:** Python 3.11, `curl_cffi`, `requests`, pytest, GitHub Actions, GitHub Pages.

**Spec:** `docs/superpowers/specs/2026-09-12-amazon-watch-multi-product-design.md` (extends `docs/superpowers/specs/2026-09-12-amazon-watch-design.md`)

## Global Constraints

- Python 3.11. No new runtime dependencies; `requirements.txt` stays `curl_cffi>=0.16.3,<0.17`, `requests>=2.31`, `tzdata>=2024.1`.
- Tests never touch the network. Every test runs offline from fixtures and fakes.
- The full suite must pass at the end of every task: `python -m pytest`.
- ASINs are `[A-Z0-9]{10}`, uppercase, and are the identity of a product everywhere.
- `products.json` is written only by `watch/manage.py`. The poll never writes it.
- One ntfy topic. Per-product routing is by the `tags` header only.
- Every ntfy header value must be ASCII; `notify._ascii` folds titles, and `products.slug` must produce ASCII by construction.
- Free values stay `FREE`, `$0.00`, `0.00`, `ILS 0.00`. Eligibility logic is not changed by this plan.
- `FAIL_ALERT_AT = 3`, `FAIL_REWARN_EVERY = 24`, applied per product.
- Data file writes stay atomic through `watch/jsonio.py`.
- Commit messages end with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

---

### Task 1: Product list module and config rename

**Files:**
- Create: `watch/products.py`
- Create: `tests/test_products.py`
- Modify: `watch/config.py`
- Modify: `tests/test_config.py`
- Modify: `watch/client.py:53` (default argument only)
- Modify: `watch/main.py:48,95` (reference rename only)
- Modify: `watch/render.py:76,86` (reference rename only)

**Interfaces:**
- Consumes: `watch.jsonio.read_json`, `watch.jsonio.write_json`.
- Produces:
  - `config.DEFAULT_ASIN: str`, `config.PRODUCTS_PATH: str`, `config.MANAGE_WORKFLOW_URL: str`, `config.product_url(asin: str) -> str`. `config.ASIN` and `config.PRODUCT_URL` no longer exist.
  - `products.ProductError(Exception)`
  - `products.load(path) -> list[dict]`
  - `products.save(path, entries: list[dict]) -> None`
  - `products.extract_asin(text: str) -> str`
  - `products.add(entries: list[dict], asin: str, label: str, when: datetime) -> list[dict]`
  - `products.remove(entries: list[dict], asin: str) -> list[dict]`
  - `products.display_label(entry: dict, title: str) -> str`
  - `products.slug(label: str, asin: str) -> str`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_products.py`:

```python
"""Product list: parsing, mutation, labels and ntfy slugs. No network."""
from datetime import datetime, timezone

import pytest

from watch import config, products

WHEN = datetime(2026, 9, 12, 18, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("text", [
    "B07W1P15GL",
    "b07w1p15gl",
    "https://www.amazon.com/dp/B07W1P15GL",
    "https://www.amazon.com/dp/B07W1P15GL?th=1&ref=foo",
    "https://www.amazon.com/gp/product/B07W1P15GL",
    "https://www.amazon.com/DI-ORO-Silicone-Ladle/dp/B07W1P15GL/ref=sr_1_3",
    "  https://amzn.to/x /dp/B07W1P15GL  ",
])
def test_extract_asin_accepts(text):
    assert products.extract_asin(text) == "B07W1P15GL"


@pytest.mark.parametrize("text", ["", "not an asin", "B07W1P15G", "https://www.amazon.com/dp/"])
def test_extract_asin_rejects(text):
    with pytest.raises(products.ProductError):
        products.extract_asin(text)


def test_add_appends_without_mutating():
    entries = []
    out = products.add(entries, "B07W1P15GL", "Ladle", WHEN)
    assert entries == []
    assert out == [{"asin": "B07W1P15GL", "label": "Ladle", "added": WHEN.isoformat()}]


def test_add_rejects_duplicate():
    entries = products.add([], "B07W1P15GL", "", WHEN)
    with pytest.raises(products.ProductError):
        products.add(entries, "B07W1P15GL", "again", WHEN)


def test_remove_drops_without_mutating():
    entries = products.add(products.add([], "B07W1P15GL", "", WHEN), "B000000001", "", WHEN)
    out = products.remove(entries, "B07W1P15GL")
    assert [e["asin"] for e in entries] == ["B07W1P15GL", "B000000001"]
    assert [e["asin"] for e in out] == ["B000000001"]


def test_remove_rejects_unknown():
    with pytest.raises(products.ProductError):
        products.remove([], "B07W1P15GL")


def test_load_bootstraps_when_missing(tmp_path):
    entries = products.load(tmp_path / "products.json")
    assert [e["asin"] for e in entries] == [config.DEFAULT_ASIN]


def test_load_bootstraps_when_unreadable(tmp_path):
    p = tmp_path / "products.json"
    p.write_text("{ not json", encoding="utf-8")
    assert [e["asin"] for e in products.load(p)] == [config.DEFAULT_ASIN]


def test_load_returns_empty_list_when_file_says_so(tmp_path):
    p = tmp_path / "products.json"
    p.write_text('{"products": []}', encoding="utf-8")
    assert products.load(p) == []


def test_save_load_round_trip(tmp_path):
    p = tmp_path / "products.json"
    entries = products.add([], "B07W1P15GL", "Ladle", WHEN)
    products.save(p, entries)
    assert products.load(p) == entries


def test_load_skips_entries_without_a_valid_asin(tmp_path):
    p = tmp_path / "products.json"
    p.write_text('{"products": [{"asin": "nope"}, {"asin": "B07W1P15GL"}]}', encoding="utf-8")
    assert [e["asin"] for e in products.load(p)] == ["B07W1P15GL"]


def test_display_label_prefers_the_label():
    entry = {"asin": "B07W1P15GL", "label": "Ladle"}
    assert products.display_label(entry, "Some Long Page Title") == "Ladle"


def test_display_label_falls_back_to_a_truncated_title():
    entry = {"asin": "B07W1P15GL", "label": ""}
    title = "x" * (products.DEFAULT_LABEL_CHARS + 20)
    out = products.display_label(entry, title)
    assert len(out) == products.DEFAULT_LABEL_CHARS + 1 and out.endswith("…")


def test_display_label_falls_back_to_the_asin():
    assert products.display_label({"asin": "B07W1P15GL", "label": ""}, "") == "B07W1P15GL"


def test_slug_folds_punctuation_and_case():
    assert products.slug("DI ORO Silicone Ladle - Soup!", "B07W1P15GL") == "di-oro-silicone-ladle-soup"


def test_slug_truncates():
    assert len(products.slug("a" * 100, "B07W1P15GL")) == products.SLUG_CHARS


def test_slug_falls_back_to_the_asin():
    assert products.slug("קומקום", "B07W1P15GL") == "b07w1p15gl"
```

Modify `tests/test_config.py` so its first two assertions read:

```python
    assert config.DEFAULT_ASIN == "B07W1P15GL"
    assert config.product_url("B07W1P15GL") == "https://www.amazon.com/dp/B07W1P15GL"
    assert config.PRODUCTS_PATH == "products.json"
    assert config.MANAGE_WORKFLOW_URL.endswith("/actions/workflows/manage.yml")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_products.py tests/test_config.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'watch.products'` and `AttributeError: module 'watch.config' has no attribute 'DEFAULT_ASIN'`.

- [ ] **Step 3: Rename the config constants**

In `watch/config.py` replace lines 6-11:

```python
# The product the watcher falls back to: it seeds products.json on a fresh checkout
# and owns any data written before the watcher understood more than one product.
DEFAULT_ASIN = "B07W1P15GL"
COUNTRY = "IL"

BASE_URL = "https://www.amazon.com"
ADDRESS_CHANGE_URL = f"{BASE_URL}/portal-migration/hz/glow/address-change?actionSource=glow"


def product_url(asin: str) -> str:
    return f"{BASE_URL}/dp/{asin}"
```

Add beside `WORKFLOW_URL`:

```python
MANAGE_WORKFLOW_URL = f"{REPO_URL}/actions/workflows/manage.yml"
```

Add beside the other paths:

```python
PRODUCTS_PATH = "products.json"
```

- [ ] **Step 4: Update the three mechanical call sites**

These keep their current behaviour; only the names change. Later tasks rewrite the logic.

- `watch/client.py:53`: `def fetch_product(asin: str = config.DEFAULT_ASIN, session=None, country: str = config.COUNTRY) -> str:`
- `watch/main.py:48`: `product: Product = parse(fetch(config.DEFAULT_ASIN))`
- `watch/main.py:95`: `click=config.product_url(config.DEFAULT_ASIN),`
- `watch/render.py:76`: `title = escape(product.get("title") or f"ASIN {config.DEFAULT_ASIN}")`
- `watch/render.py:86`: `f'<h1><a href="{escape(config.product_url(config.DEFAULT_ASIN))}">{title}</a></h1>',`

In `tests/test_main.py`, replace both `config.PRODUCT_URL` references with `config.product_url(config.DEFAULT_ASIN)`.

- [ ] **Step 5: Write `watch/products.py`**

```python
"""The list of watched products, and the labels and tags derived from it.

products.json is the source of truth for what the watcher polls. Only
watch/manage.py writes it; the poll reads it and never changes it, so a label a
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
    if any(e["asin"] == asin for e in entries):
        raise ProductError(f"{asin} is already being watched")
    return list(entries) + [{"asin": asin, "label": (label or "").strip(), "added": when.isoformat()}]


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
```

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS, with the new `tests/test_products.py` cases included.

- [ ] **Step 7: Commit**

```bash
git add watch/products.py watch/config.py watch/client.py watch/main.py watch/render.py tests/test_products.py tests/test_config.py tests/test_main.py
git commit -m "feat: product list module and per-product config helpers

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Per-product state and history

**Files:**
- Modify: `watch/state.py`
- Modify: `watch/history.py`
- Modify: `tests/test_state.py`
- Modify: `tests/test_history.py`
- Modify: `watch/main.py` (call sites only, keep single-product behaviour green)
- Modify: `watch/render.py` (read the migrated shape, keep the single-product page green)
- Modify: `tests/test_main.py`, `tests/test_render.py` (shape of the state dict they build)

**Interfaces:**
- Consumes: `config.DEFAULT_ASIN`, `watch.jsonio`.
- Produces:
  - `state.default_state() -> dict` — `{"version": 2, "last_checked": None, "products": {}}`
  - `state.default_entry() -> dict` — `{"free": None, "title": "", "delivery_text": "", "merchant": "", "checked_at": None, "last_success": None, "fail_count": 0, "last_error": None}`
  - `state.load(path) -> dict`, `state.save(path, state) -> None`
  - `state.entry(state, asin) -> dict` — the live entry, inserted if absent
  - `state.prune(state, keep_asins) -> None` — mutates, drops unwatched entries
  - `history.append_flip(entries, when, asin, free, delivery_text) -> None`
  - `history.for_asin(entries, asin) -> list[dict]`
  - `history.load`/`history.save` unchanged in signature

**Note for the implementer:** Task 4 rewrites `main.py` and Task 5 rewrites `render.py`. Here you only keep them compiling and green against the new state shape — the smallest edit that does that is right. `main.run` should read and write `st["products"][config.DEFAULT_ASIN]` where it used `st["product"]`, and `render_page` should read the same entry. Do not add multi-product behaviour to either.

- [ ] **Step 1: Write the failing tests**

Replace `tests/test_state.py` with:

```python
"""State persistence, including migration from the single-product format."""
import json

from watch import config, state


def test_load_missing_file_gives_defaults(tmp_path):
    st = state.load(tmp_path / "state.json")
    assert st == {"version": 2, "last_checked": None, "products": {}}


def test_load_unreadable_file_gives_defaults(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{ not json", encoding="utf-8")
    assert state.load(p)["products"] == {}


def test_round_trip(tmp_path):
    p = tmp_path / "state.json"
    st = state.default_state()
    st["last_checked"] = "2026-09-12T10:00:00+00:00"
    e = state.entry(st, "B07W1P15GL")
    e["free"] = True
    e["title"] = "Ladle"
    state.save(p, st)
    assert state.load(p) == st


def test_version_1_file_migrates_under_the_default_asin(tmp_path):
    p = tmp_path / "state.json"
    p.write_text(json.dumps({
        "last_checked": "2026-09-12T17:50:06+00:00",
        "last_success": "2026-09-12T17:50:06+00:00",
        "fail_count": 2,
        "last_error": "boom",
        "product": {
            "checked_at": "2026-09-12T17:50:06+00:00",
            "delivery_text": "$19.28",
            "free": False,
            "merchant": "",
            "title": "DI ORO Silicone Ladle",
        },
    }), encoding="utf-8")
    st = state.load(p)
    assert st["version"] == 2
    assert st["last_checked"] == "2026-09-12T17:50:06+00:00"
    assert "product" not in st
    e = st["products"][config.DEFAULT_ASIN]
    assert e["free"] is False
    assert e["title"] == "DI ORO Silicone Ladle"
    assert e["delivery_text"] == "$19.28"
    assert e["fail_count"] == 2
    assert e["last_error"] == "boom"
    assert e["last_success"] == "2026-09-12T17:50:06+00:00"
    assert e["checked_at"] == "2026-09-12T17:50:06+00:00"


def test_version_1_file_without_a_product_migrates_to_empty(tmp_path):
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"last_checked": "2026-09-12T17:50:06+00:00", "product": None}),
                 encoding="utf-8")
    st = state.load(p)
    assert st["products"] == {}
    assert st["last_checked"] == "2026-09-12T17:50:06+00:00"


def test_entry_inserts_a_default_and_returns_the_live_dict():
    st = state.default_state()
    e = state.entry(st, "B07W1P15GL")
    assert e == state.default_entry()
    e["free"] = True
    assert st["products"]["B07W1P15GL"]["free"] is True


def test_prune_drops_unwatched_products():
    st = state.default_state()
    state.entry(st, "B07W1P15GL")
    state.entry(st, "B000000001")
    state.prune(st, ["B000000001"])
    assert list(st["products"]) == ["B000000001"]
```

Replace `tests/test_history.py` with:

```python
"""History records one flip per product."""
import json
from datetime import datetime, timezone

from watch import config, history

NOW = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)


def test_append_flip_records_the_asin():
    entries = []
    history.append_flip(entries, NOW, "B07W1P15GL", True, "FREE")
    assert entries == [{
        "at": NOW.isoformat(), "asin": "B07W1P15GL", "free": True, "delivery_text": "FREE",
    }]


def test_round_trip(tmp_path):
    p = tmp_path / "history.json"
    entries = []
    history.append_flip(entries, NOW, "B07W1P15GL", False, "$19.28")
    history.save(p, entries)
    assert history.load(p) == entries


def test_missing_file_loads_empty(tmp_path):
    assert history.load(tmp_path / "history.json") == []


def test_version_1_entries_belong_to_the_default_asin(tmp_path):
    p = tmp_path / "history.json"
    p.write_text(json.dumps([{"at": NOW.isoformat(), "free": False, "delivery_text": "ILS 58.91"}]),
                 encoding="utf-8")
    assert history.load(p)[0]["asin"] == config.DEFAULT_ASIN


def test_for_asin_filters():
    entries = []
    history.append_flip(entries, NOW, "B07W1P15GL", True, "FREE")
    history.append_flip(entries, NOW, "B000000001", False, "$5.00")
    assert [e["asin"] for e in history.for_asin(entries, "B000000001")] == ["B000000001"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_state.py tests/test_history.py -q`
Expected: FAIL — `KeyError: 'version'`, `AttributeError: module 'watch.state' has no attribute 'entry'`, and `append_flip()` taking the wrong number of arguments.

- [ ] **Step 3: Rewrite `watch/state.py`**

```python
"""Persist watcher state between polls as JSON, one entry per watched product."""
from __future__ import annotations

from pathlib import Path

from watch import config
from watch.jsonio import read_json, write_json

VERSION = 2


def default_state() -> dict:
    return {
        "version": VERSION,
        "last_checked": None,   # ISO datetime (UTC) of the last poll cycle
        "products": {},         # ASIN -> entry
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
```

- [ ] **Step 4: Rewrite `watch/history.py`**

```python
"""Record every change of free-shipping eligibility as a flat list of flips."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from watch import config
from watch.jsonio import read_json, write_json


def load(path: str | Path) -> list[dict]:
    """Every recorded flip. Entries written before products had ASINs get the default one."""
    data = read_json(path, [], "history")
    if not isinstance(data, list):
        return []
    out = []
    for e in data:
        if not isinstance(e, dict):
            continue
        out.append({**e, "asin": e.get("asin") or config.DEFAULT_ASIN})
    return out


def save(path: str | Path, entries: list[dict]) -> None:
    write_json(path, entries)


def append_flip(entries: list[dict], when: datetime, asin: str,
                free: bool, delivery_text: str) -> None:
    entries.append({
        "at": when.isoformat(),
        "asin": asin,
        "free": bool(free),
        "delivery_text": delivery_text,
    })


def for_asin(entries: list[dict], asin: str) -> list[dict]:
    return [e for e in entries if e.get("asin") == asin]
```

- [ ] **Step 5: Keep `main.py` and `render.py` compiling**

In `watch/main.py`, the smallest edit that keeps today's single-product behaviour:

- `_finish` is unchanged.
- Replace `st["fail_count"] = ...` / `st["last_error"] = ...` / `st["last_success"] = ...` / `st["product"] = ...` / `previous = st.get("product")` with reads and writes of `e = state_mod.entry(st, config.DEFAULT_ASIN)` — `e["fail_count"]`, `e["last_error"]`, `e["last_success"]`, `e["free"]` and the parsed fields.
- `history_mod.append_flip(history, now, config.DEFAULT_ASIN, product.free, product.delivery_text)`.
- `run` still returns `st`.

In `watch/render.py`, `product = (state.get("products") or {}).get(config.DEFAULT_ASIN) or {}`, and read `fail_count` / `last_error` / `last_success` from that same dict rather than from the top level.

Update `tests/test_main.py` and `tests/test_render.py` where they assert on the state shape: `st["product"]["free"]` becomes `st["products"][config.DEFAULT_ASIN]["free"]`, `st["fail_count"]` becomes `st["products"][config.DEFAULT_ASIN]["fail_count"]`, and the hand-built state dicts in `tests/test_render.py` move under `{"version": 2, "products": {config.DEFAULT_ASIN: {...}}}`. History assertions gain the `asin` field. Do not change what those tests are testing.

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add watch/state.py watch/history.py watch/main.py watch/render.py tests/
git commit -m "feat: key state and history by ASIN, migrating the old files

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: One Israel handshake per cycle

**Files:**
- Modify: `watch/client.py`
- Modify: `tests/test_client.py`

**Interfaces:**
- Consumes: `config.DEFAULT_ASIN`, `config.COUNTRY`, `config.BASE_URL`, `config.ADDRESS_CHANGE_URL`, `config.product_url`.
- Produces:
  - `client.set_israel(session, asin: str = config.DEFAULT_ASIN, country: str = config.COUNTRY) -> None`
  - `client.fetch_page(session, asin: str) -> str`
  - `client.fetch_product(asin=config.DEFAULT_ASIN, session=None, country=config.COUNTRY) -> str` (unchanged behaviour, now composed of the two)
  - `client.new_session()`, `client.FetchError` unchanged.

**Note for the implementer:** read `tests/test_client.py` first. It already has a fake session recording calls; extend that fake rather than writing a second one. `set_israel` must not check the glow line — `fetch_page` does that on every page, so a session that loses its Israel context mid-cycle is caught.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_client.py`, keeping the existing cases and the existing fake session:

```python
def test_set_israel_posts_the_token_and_returns_none(...):
    """First GET, token extracted, address-change POSTed with it; returns None."""


def test_set_israel_raises_when_the_token_is_missing(...):
    """A page with no anti-csrftoken-a2z raises FetchError mentioning the token."""


def test_set_israel_raises_when_the_address_is_not_updated(...):
    """An address-change body without isAddressUpdated:1 raises FetchError."""


def test_fetch_page_returns_the_body(...):
    """One GET only; the returned HTML is the body of that GET."""


def test_fetch_page_raises_on_captcha(...):
def test_fetch_page_raises_on_a_short_body(...):
def test_fetch_page_raises_when_the_glow_line_is_not_israel(...):


def test_fetch_product_still_works_end_to_end(...):
    """set_israel then fetch_page on one session; three requests in total."""
```

Write these as real tests against the existing fake, asserting on the recorded call sequence (`[("get", url), ("post", url), ("get", url)]` for `fetch_product`, and a single `("get", url)` for `fetch_page`).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_client.py -q`
Expected: FAIL — `AttributeError: module 'watch.client' has no attribute 'set_israel'`.

- [ ] **Step 3: Split `fetch_product`**

Replace `watch/client.py:53-93` with:

```python
def set_israel(session, asin: str = config.DEFAULT_ASIN,
               country: str = config.COUNTRY) -> None:
    """Put this session's ship-to country into `country`.

    One handshake serves a whole poll cycle: Amazon keeps the choice in the
    session's cookies, so every later page fetched on the same session is already
    rendered for that country. Verification is left to fetch_page, which checks
    the glow line on every page it returns.
    """
    url = config.product_url(asin)
    first = _check_page(session.get(url, timeout=TIMEOUT), "first GET")
    m = TOKEN_RE.search(first)
    if not m:
        raise FetchError("token: anti-csrftoken-a2z not found in page")

    resp = session.post(
        config.ADDRESS_CHANGE_URL,
        data={
            "locationType": "COUNTRY",
            "countryCode": country,
            "deviceType": "web",
            "storeContext": "generic",
            "pageType": "Detail",
            "actionSource": "glow",
        },
        headers={
            "anti-csrftoken-a2z": m.group(1),
            "Referer": url,
            "X-Requested-With": "XMLHttpRequest",
        },
        timeout=TIMEOUT,
    )
    if resp.status_code != 200:
        raise FetchError(f"address-change: HTTP {resp.status_code}")
    if not ADDRESS_UPDATED_RE.search(resp.text):
        raise FetchError(f"address-change: not updated: {resp.text[:200]}")
    log.info("ship-to country set to %s", country)


def fetch_page(session, asin: str) -> str:
    """One product page, verified to have been rendered for the Israel context."""
    html = _check_page(session.get(config.product_url(asin), timeout=TIMEOUT), f"GET {asin}")
    g = GLOW_RE.search(html)
    if not g or "israel" not in g.group(1).lower():
        found = g.group(1).strip() if g else "(no glow line)"
        raise FetchError(f"glow: ship-to country is not Israel: {found}")
    log.info("fetched %s in Israel context (%d characters)", asin, len(html))
    return html


def fetch_product(asin: str = config.DEFAULT_ASIN, session=None,
                  country: str = config.COUNTRY) -> str:
    """One product page from a fresh session. For one-off use; the poll reuses a session."""
    s = session or new_session()
    set_israel(s, asin, country)
    return fetch_page(s, asin)
```

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add watch/client.py tests/test_client.py
git commit -m "refactor: split the Israel handshake from the page fetch

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Poll every watched product

**Files:**
- Modify: `watch/main.py`
- Modify: `tests/test_main.py`

**Interfaces:**
- Consumes: `products.load/display_label/slug`, `state.load/save/entry/prune`, `history.load/save/append_flip`, `client.new_session/set_israel/fetch_page/FetchError`, `parser.parse/ParseError`, `render.render_page(state, history, product_list, now)` (the third parameter is named `product_list`, not `products`, because `render.py` imports the `products` module).
- Produces: `main.run(fetch=None, notifier=notify.send, products_path=..., state_path=..., history_path=..., page_path=..., now=None) -> dict`. `fetch` keeps the signature `fetch(asin) -> str`.

**Note for the implementer:** Task 5 rewrites `render.py` to take the new fourth argument. Call `render_page(st, history, entries, now)` here; if `render.py` still has the three-argument signature when you start, add the parameter to it and ignore it — do not build the cards, that is Task 5.

- [ ] **Step 1: Write the failing tests**

Rewrite `tests/test_main.py`. Keep every existing case, adapted to the new shape, and add:

```python
TWO = [
    {"asin": "B07W1P15GL", "label": "Ladle", "added": ""},
    {"asin": "B000000001", "label": "Kettle", "added": ""},
]


def write_products(tmp_path, entries):
    from watch import products
    products.save(tmp_path / "products.json", entries)
    return tmp_path / "products.json"


def by_asin(html_for):
    """A fake fetch that returns different HTML per ASIN."""
    return lambda asin: html_for[asin]


def test_each_product_flips_independently(tmp_path):
    """Ladle goes free, Kettle stays paid: exactly one push, tagged for the Ladle."""


def test_pushes_carry_a_per_product_tag(tmp_path):
    """tags == "package,ladle" and the title is "FREE: Ladle"."""


def test_one_product_failing_keeps_its_data_and_updates_the_other(tmp_path):
    """The failing product keeps its previous free/title; the other one advances."""


def test_all_products_failing_sends_one_combined_warning(tmp_path):
    """Three failing cycles over two products send exactly one push titled
    "Amazon watcher failing" with tags "warning"."""


def test_one_product_failing_sends_one_tagged_warning(tmp_path):
    """Three failing cycles for one of two products send exactly one push titled
    "Amazon watcher failing: Kettle" with tags "warning,kettle"."""


def test_empty_product_list_writes_the_page_and_sends_nothing(tmp_path):
    """No products: no pushes, state has no product entries, the page exists."""


def test_removing_a_product_drops_its_state(tmp_path):
    """Poll two, rewrite products.json with one, poll again: state has one entry."""


def test_handshake_failure_fails_every_product(tmp_path):
    """A fetch that raises FetchError for every ASIN counts a failure per product."""
```

Write these as real tests with real assertions, using the existing `FakeNotifier` and fixture HTML. The single-product cases keep their current meaning: first poll records without a push, paid to free pushes once, free to paid is silent, a lost state file re-announces.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_main.py -q`
Expected: FAIL — `run()` does not accept `products_path`.

- [ ] **Step 3: Rewrite `watch/main.py`**

```python
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
            # records the failure, and the combined rule below decides the alert.
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
        # Every product failed at once, which is a captcha or a network problem
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
```

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add watch/main.py watch/render.py tests/test_main.py
git commit -m "feat: poll every watched product in one cycle

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: One status card per product

**Files:**
- Modify: `watch/render.py`
- Modify: `tests/test_render.py`

**Interfaces:**
- Consumes: `state` (version 2 shape), `history` (with ASINs), the product list from `products.load`, `products.display_label`, `history.for_asin`, `config.product_url`, `config.MANAGE_WORKFLOW_URL`, `config.WORKFLOW_URL`, `config.POLL_INTERVAL_SECONDS`, `config.DISPLAY_TZ`.
- Produces: `render.render_page(state: dict, history: list[dict], product_list: list[dict], now: datetime) -> str`.

**Note for the implementer:** `_parse`, `_local`, `_fmt`, `LOCAL_TZ` and the `STYLE` block already exist and work — keep them, add to `STYLE` rather than replacing it. Every timestamp stays Jerusalem local with UTC beside it. Nothing may raise: a malformed state entry must render as "No data yet", not a traceback.

- [ ] **Step 1: Write the failing tests**

Rewrite `tests/test_render.py`, keeping the existing cases about timestamps, the refresh meta, the "Check now" button and the "Next automatic check" line, and adding:

```python
def test_a_card_per_product():
    """Two products, two labels, two badges on the page."""


def test_free_products_sort_first():
    """The free product's label appears before the paid one's in the HTML."""


def test_a_card_shows_its_own_history_only():
    """The Ladle card holds the Ladle's delivery text and not the Kettle's."""


def test_a_failing_product_shows_its_warning_on_its_own_card():
    """The failure count appears once, and the healthy product has no warning."""


def test_labels_fall_back_to_the_page_title():
    """An entry with no label renders the state title."""


def test_the_manage_button_is_present():
    """config.MANAGE_WORKFLOW_URL appears in an anchor, with explanatory text."""


def test_an_empty_product_list_still_renders_the_buttons():
    """No products: a "nothing watched" line plus both buttons, no traceback."""


def test_a_malformed_entry_renders_as_unknown():
    """A product whose state entry is missing renders the "No data yet" badge."""
```

Write them as real tests with real assertions against the returned HTML.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_render.py -q`
Expected: FAIL — `render_page()` missing the `products` argument, and no manage button in the output.

- [ ] **Step 3: Rewrite the body of `watch/render.py`**

Keep the module docstring, the `LOCAL_TZ` block, `_parse`, `_local` and `_fmt`. Add to `STYLE`:

```python
.card { background: #fff; border: 1px solid #e2e2e2; border-radius: .6rem;
        padding: .9rem 1rem; margin: 1rem 0; }
.card h2 { font-size: 1.05rem; margin: 0 0 .4rem; }
.card h2 a { color: inherit; }
.card .badge { font-size: 1.1rem; }
.empty { color: #555; font-style: italic; margin: 1.5rem 0; }
```

Replace `render_page` with:

```python
def _badge(free) -> tuple[str, str]:
    if free is True:
        return "free", "FREE shipping to Israel"
    if free is False:
        return "paid", "Paid shipping"
    return "unknown", "No data yet"


def _card(entry: dict, ps: dict, rows: list[dict]) -> str:
    asin = entry.get("asin", "")
    label = escape(products.display_label(entry, ps.get("title") or ""))
    cls, badge = _badge(ps.get("free"))
    out = [
        '<div class="card">',
        f'<h2><a href="{escape(config.product_url(asin))}">{label}</a></h2>',
        f'<div class="badge {cls}">{badge}</div>',
    ]
    delivery = escape(ps.get("delivery_text") or "")
    if delivery:
        out.append(f'<p class="meta">Delivery: {delivery}</p>')
    merchant = escape(ps.get("merchant") or "")
    if merchant:
        out.append(f'<p class="meta">{merchant}</p>')
    out.append(f'<p class="meta">Last good reading: {_fmt(ps.get("last_success"))}</p>')
    fails = int(ps.get("fail_count") or 0)
    if fails > 0:
        err = escape(str(ps.get("last_error") or ""))
        out.append(f'<div class="warn">{fails} consecutive failed polls. Last error: {err}</div>')
    if rows:
        out.append("<table><tr><th>When</th><th>State</th><th>Delivery</th></tr>")
        for e in reversed(rows):
            when = _parse(e.get("at"))
            shown = _local(when) if when else escape(str(e.get("at") or ""))
            out.append(
                f"<tr><td>{shown}</td><td>{'FREE' if e.get('free') else 'Paid'}</td>"
                f"<td>{escape(str(e.get('delivery_text') or ''))}</td></tr>"
            )
        out.append("</table>")
    out.append("</div>")
    return "\n".join(out)


def render_page(state: dict, history: list[dict], product_list: list[dict],
                now: datetime) -> str:
    entries = state.get("products") or {}
    parts = [
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">",
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
        '<meta http-equiv="refresh" content="600">',
        "<title>Amazon free-shipping watch</title>",
        f"<style>{STYLE}</style></head><body>",
        "<h1>Free shipping to Israel</h1>",
    ]

    # Free first, then the order products were added: whatever is buyable now is
    # what the page is for, so it goes at the top where a phone shows it.
    ordered = sorted(
        enumerate(product_list),
        key=lambda item: (0 if (entries.get(item[1].get("asin")) or {}).get("free") is True else 1,
                          item[0]),
    )
    if ordered:
        for _, entry in ordered:
            asin = entry.get("asin", "")
            parts.append(_card(entry, entries.get(asin) or {}, history_mod.for_asin(history, asin)))
    else:
        parts.append('<p class="empty">No products are being watched.</p>')

    last_checked = _parse(state.get("last_checked"))
    next_line = ""
    if last_checked is not None:
        nxt = last_checked + timedelta(seconds=config.POLL_INTERVAL_SECONDS)
        next_line = f"Next automatic check: about {_local(nxt)}<br>"
    parts.append(
        f'<p class="meta">Last checked: {_fmt(state.get("last_checked"))}<br>'
        f'{next_line}'
        f'Page rendered: {_fmt(now.isoformat())}</p>'
    )
    parts.append(
        f'<a class="check" href="{escape(config.WORKFLOW_URL)}">Check now</a>'
        '<p class="meta">Opens GitHub Actions. Tap "Run workflow" there, then reload this page '
        'in about a minute. A manual run also restarts the hourly cycle.</p>'
    )
    parts.append(
        f'<a class="check" href="{escape(config.MANAGE_WORKFLOW_URL)}">Manage products</a>'
        '<p class="meta">Opens GitHub Actions. Tap "Run workflow", choose add or remove, and '
        'paste an ASIN or an Amazon link. The next check starts by itself.</p>'
    )
    parts.append(
        f'<p class="meta">Times are {escape(config.DISPLAY_TZ.split("/")[-1])} local unless '
        'marked UTC.</p>'
    )
    parts.append("</body></html>")
    return "\n".join(parts)
```

Add `from watch import config, history as history_mod, products` to the imports.

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add watch/render.py tests/test_render.py
git commit -m "feat: one status card per watched product

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Add and remove from a phone

**Files:**
- Create: `watch/manage.py`
- Create: `tests/test_manage.py`
- Create: `.github/workflows/manage.yml`
- Create: `products.json`
- Modify: `.github/workflows/poll.yml`

**Interfaces:**
- Consumes: `products.load/save/add/remove/extract_asin/ProductError`, `config.PRODUCTS_PATH`.
- Produces: `manage.main(argv: list[str] | None = None) -> int`, run as `python -m watch.manage`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_manage.py`:

```python
"""The add/remove command line. No network."""
import json

from watch import manage, products


def test_add_writes_the_file(tmp_path, capsys):
    p = tmp_path / "products.json"
    products.save(p, [])
    assert manage.main(["--action", "add", "--product",
                        "https://www.amazon.com/dp/B07W1P15GL", "--label", "Ladle",
                        "--path", str(p)]) == 0
    assert products.load(p) == [
        {"asin": "B07W1P15GL", "label": "Ladle", "added": products.load(p)[0]["added"]}
    ]
    assert "B07W1P15GL" in capsys.readouterr().out


def test_add_without_a_label_stores_an_empty_one(tmp_path):
    p = tmp_path / "products.json"
    products.save(p, [])
    manage.main(["--action", "add", "--product", "B07W1P15GL", "--path", str(p)])
    assert products.load(p)[0]["label"] == ""


def test_remove_writes_the_file(tmp_path):
    p = tmp_path / "products.json"
    products.save(p, [{"asin": "B07W1P15GL", "label": "", "added": ""}])
    assert manage.main(["--action", "remove", "--product", "B07W1P15GL", "--path", str(p)]) == 0
    assert products.load(p) == []


def test_a_bad_product_string_fails_and_leaves_the_file_alone(tmp_path, capsys):
    p = tmp_path / "products.json"
    products.save(p, [{"asin": "B07W1P15GL", "label": "", "added": ""}])
    before = p.read_text(encoding="utf-8")
    assert manage.main(["--action", "add", "--product", "nonsense", "--path", str(p)]) == 1
    assert p.read_text(encoding="utf-8") == before
    assert "nonsense" in capsys.readouterr().err


def test_a_duplicate_fails_and_leaves_the_file_alone(tmp_path):
    p = tmp_path / "products.json"
    products.save(p, [{"asin": "B07W1P15GL", "label": "", "added": ""}])
    before = p.read_text(encoding="utf-8")
    assert manage.main(["--action", "add", "--product", "B07W1P15GL", "--path", str(p)]) == 1
    assert p.read_text(encoding="utf-8") == before


def test_removing_an_unwatched_product_fails(tmp_path):
    p = tmp_path / "products.json"
    products.save(p, [])
    assert manage.main(["--action", "remove", "--product", "B07W1P15GL", "--path", str(p)]) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_manage.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'watch.manage'`.

- [ ] **Step 3: Write `watch/manage.py`**

```python
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
        if args.action == "add":
            asin = products.extract_asin(args.product)
            entries = products.add(entries, asin, args.label, datetime.now(timezone.utc))
        else:
            asin = products.extract_asin(args.product)
            entries = products.remove(entries, asin)
    except products.ProductError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    products.save(args.path, entries)
    print(f"{args.action}: {asin} ({len(entries)} product(s) watched)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Create `products.json` with the product watched today**

```json
{
  "products": [
    {
      "asin": "B07W1P15GL",
      "label": "DI ORO Silicone Ladle",
      "added": "2026-09-12T00:00:00+00:00"
    }
  ]
}
```

- [ ] **Step 5: Create `.github/workflows/manage.yml`**

```yaml
name: manage

# Add or remove a watched product from a phone: Run workflow, pick add or remove,
# paste an ASIN or an Amazon link. The commit this makes matches poll.yml's push
# filter, which cancels the sleeping poll job and starts a fresh one, so the new
# product shows up on the status page about a minute later.
on:
  workflow_dispatch:
    inputs:
      action:
        description: "Add or remove"
        type: choice
        options: [add, remove]
        required: true
        default: add
      product:
        description: "ASIN or Amazon product URL"
        required: true
      label:
        description: "Name to show on the page and in notifications (optional)"
        required: false
        default: ""

permissions:
  contents: write

concurrency:
  group: manage

jobs:
  manage:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Apply the change
        run: |
          python -m watch.manage \
            --action "${{ inputs.action }}" \
            --product "${{ inputs.product }}" \
            --label "${{ inputs.label }}"

      - name: Commit and push
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add products.json
          if git diff --cached --quiet; then
            echo "products.json unchanged"
          else
            git commit -q -m "chore: ${{ inputs.action }} product ${{ inputs.product }}"
            git push -q origin HEAD:main
          fi
```

- [ ] **Step 6: Update `.github/workflows/poll.yml`**

Two edits:

- Add `- "products.json"` to the `push.paths` list, so a manage commit restarts the poll loop.
- Add `products.json` to the `git add --all --` line, so a poll that races a manage run stages it rather than leaving it behind. The poll never writes the file, so this normally stages nothing.

- [ ] **Step 7: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add watch/manage.py tests/test_manage.py .github/workflows/manage.yml .github/workflows/poll.yml products.json
git commit -m "feat: add and remove products through a workflow

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Documentation

**Files:**
- Modify: `README.md`
- Modify: `scripts/capture_fixture.py` (only if it references `config.ASIN` or `config.PRODUCT_URL`)

**Interfaces:**
- Consumes: everything above. Produces: nothing other tasks depend on.

- [ ] **Step 1: Check the script still runs**

Run: `grep -rn "config.ASIN\|config.PRODUCT_URL" scripts/ watch/ tests/`
Expected: no matches. Fix any that appear, using `config.DEFAULT_ASIN` and `config.product_url(asin)`.

- [ ] **Step 2: Update `README.md`**

Rewrite the "Watching" line and the "How it works" list so they describe the list of products rather than one ASIN. Cover, in the project's existing voice:

- `products.json` is the list of watched products, and the `manage` workflow is how it changes. Editing the file by hand and pushing works too.
- Adding a product needs an ASIN or any Amazon product URL; the label is optional and falls back to the page title.
- One ntfy topic carries everything; each push is tagged with the product, so the ntfy app can filter or mute per product.
- A cycle costs two requests plus one per product.
- The status page shows a card per product, free ones first, with "Check now" and "Manage products" buttons.
- Failure alerts are per product, with one combined alert when everything fails at once.

Keep the setup section, the local development section and the fetch explanation.

- [ ] **Step 3: Run the full suite one last time**

Run: `python -m pytest -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add README.md scripts/
git commit -m "docs: describe the multi-product watcher

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```
