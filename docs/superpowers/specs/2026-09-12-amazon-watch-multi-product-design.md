# Amazon watcher: multiple products: design

Date: 2026-09-12. Status: approved in chat, ready for implementation planning.

Extends `2026-09-12-amazon-watch-design.md`. Everything in that document still
holds except where this one replaces it. The fetch method, the eligibility rule,
the free values, the notification channel and the hourly cadence are unchanged.

## Goal

Watch any number of Amazon products instead of one, and let the user add and
remove products from a phone without editing files or holding a GitHub token.
One ntfy topic still carries every alert; each alert is tagged with the product
it belongs to so the notifications can be told apart and filtered.

## Decisions

| Question | Decision |
|---|---|
| Product list | `products.json` in the repository root, committed like the other data files. |
| Add and remove | A `manage` workflow with `workflow_dispatch` inputs. The status page links to it, the same way the "Check now" button links to `poll`. |
| Product identity | The ASIN. It is the key in state, in history, and in `products.json`. |
| Labels | Optional and user-supplied at add time. When absent, the product's page title from the last successful poll is used, and the ASIN when there is no title yet. `products.json` is never written by the poll. |
| Notification routing | One topic, as today. Each push carries a per-product ntfy tag. Per-product topics were considered and rejected: every topic needs subscribing by hand, which defeats the two-tap add flow. |
| Requests per cycle | The ship-to Israel context is set once per cycle and the session is reused, so a cycle costs 2 requests plus 1 per product. |
| Failure alerts | Per product, with one combined alert when every product is failing at once (a captcha or network problem, not a product problem). |
| Migration | Automatic and silent on the first poll after deploy. No manual step, no data loss. |

## Data files

### `products.json`

```json
{
  "products": [
    { "asin": "B07W1P15GL", "label": "", "added": "2026-09-12T18:00:00+00:00" }
  ]
}
```

- `asin`: ten characters, `[A-Z0-9]{10}`, unique in the list. Required.
- `label`: user-supplied display name, or `""`. Never written by the poll.
- `added`: ISO 8601 UTC timestamp of when the product was added.

The list order is the order products were added, and is the order they were
added in on the page as well, except that free products sort first.

When the file is missing or unreadable, the watcher bootstraps it in memory from
`config.DEFAULT_ASIN` so a fresh checkout still watches the original product. It
does not write the file in that case; `manage` is the only writer.

### `state.json` (version 2)

```json
{
  "version": 2,
  "last_checked": "2026-09-12T18:00:00+00:00",
  "products": {
    "B07W1P15GL": {
      "free": false,
      "title": "DI ORO Silicone Ladle ...",
      "delivery_text": "$19.28",
      "merchant": "",
      "checked_at": "2026-09-12T18:00:00+00:00",
      "last_success": "2026-09-12T18:00:00+00:00",
      "fail_count": 0,
      "last_error": null
    }
  }
}
```

`last_checked` stays global: it is when the cycle ran. Everything else is per
product, because one product failing says nothing about the others.

A version 1 state file — the flat one with a top-level `product`, `fail_count`,
`last_error` and `last_success` — is migrated on read: its `product` block plus
those three fields become the entry for `config.DEFAULT_ASIN`. A state file with
neither `version` nor `product` is treated as empty.

Entries for ASINs no longer in `products.json` are dropped on save, so removing
a product cleans up after itself.

### `history.json` (version 2)

A flat list, newest last, as today, with an `asin` field added:

```json
[{ "at": "2026-09-12T16:01:36+00:00", "asin": "B07W1P15GL", "free": false, "delivery_text": "ILS 58.91" }]
```

Entries without an `asin` are version 1 entries and are read as belonging to
`config.DEFAULT_ASIN`. History is never pruned when a product is removed: the
record of what happened stays, and the page shows it only while the product is
watched.

## Components

### `products.py` (new)

```python
DEFAULT_LABEL_CHARS = 60   # a page title is truncated to this for display
SLUG_CHARS = 30            # maximum length of an ntfy tag slug

class ProductError(Exception): ...          # bad ASIN, duplicate, not found

def load(path) -> list[dict]                # entries, bootstrapped when absent
def save(path, entries: list[dict]) -> None # writes {"products": entries}
def extract_asin(text: str) -> str          # from a bare ASIN or an Amazon URL
def add(entries, asin, label, when) -> list[dict]
def remove(entries, asin) -> list[dict]
def display_label(entry: dict, title: str) -> str
def slug(label: str, asin: str) -> str      # ntfy tag, ASCII, lowercase
```

`extract_asin` accepts a bare ASIN, `/dp/<asin>`, `/gp/product/<asin>`, and any
URL containing one of those, with or without query string, case-insensitively,
and uppercases the result. Anything else raises `ProductError`.

`add` raises `ProductError` on a duplicate ASIN. `remove` raises `ProductError`
when the ASIN is not in the list. Both return a new list and do not mutate.

`display_label` returns the entry's label when it has one, the title truncated
to `DEFAULT_LABEL_CHARS` when it does not, and the ASIN when there is no title.

`slug` lowercases, replaces every run of non-alphanumeric characters with a
single `-`, strips leading and trailing `-`, truncates to `SLUG_CHARS`, and
falls back to the lowercased ASIN when nothing is left. The result is ASCII, so
a Hebrew or accented label cannot break the ntfy header.

### `config.py`

- `ASIN` is renamed `DEFAULT_ASIN`. It is the bootstrap and migration product,
  not the watched product.
- `PRODUCT_URL` becomes `product_url(asin)`.
- `PRODUCTS_PATH = "products.json"` is added.
- `MANAGE_WORKFLOW_URL = f"{REPO_URL}/actions/workflows/manage.yml"` is added.

### `client.py`

The single `fetch_product` is split so one glow handshake serves a whole cycle:

```python
def set_israel(session, asin=config.DEFAULT_ASIN, country=config.COUNTRY) -> None
def fetch_page(session, asin: str) -> str
def fetch_product(asin=config.DEFAULT_ASIN, session=None, country=config.COUNTRY) -> str
```

`set_israel` does the first GET, extracts the token, POSTs the address change
and raises `FetchError` on any failure, exactly as the second and third steps of
today's `fetch_product` do. It does not verify the glow line; `fetch_page` does.

`fetch_page` does one GET, runs the existing size and captcha checks, verifies
that `glow-ingress-line2` names Israel, and returns the HTML. Verifying on every
page rather than once per cycle costs nothing and catches a session that loses
its context part-way through a cycle.

`fetch_product` keeps working for one-off use (`scripts/capture_fixture.py`, a
single manual run) as `set_israel` followed by `fetch_page` on one session.

A cycle therefore costs 2 requests for the handshake plus 1 per product. Ten
products is 12 requests an hour.

### `state.py`

```python
def default_state() -> dict                        # {"version": 2, "last_checked": None, "products": {}}
def default_entry() -> dict
def load(path) -> dict                             # migrates version 1
def save(path, state, keep_asins=None) -> None     # drops entries not in keep_asins
def entry(state, asin) -> dict                     # existing entry or a fresh default
```

`save` with `keep_asins=None` keeps everything, so callers that do not know the
product list cannot accidentally delete state.

### `history.py`

```python
def load(path) -> list[dict]                       # fills a missing asin with DEFAULT_ASIN
def save(path, entries) -> None
def append_flip(entries, when, asin, free, delivery_text) -> None
def for_asin(entries, asin) -> list[dict]
```

### `notify.py`

Unchanged in behaviour. It already takes `tags`; the callers now pass a
per-product value.

### `main.py`

One cycle:

1. Load `products.json`, `state.json`, `history.json`.
2. Build a session and call `set_israel` once. If that raises, every product is
   recorded as failed with that error and the combined-failure rule below
   decides whether to warn. The page is still rendered.
3. For each product in list order: fetch, parse, compare with the stored `free`.
   - A first observation (no stored entry, or a lost state file) appends history
     and announces when the product is free, as today.
   - A flip to free appends history and announces. A flip to paid appends
     history and stays silent.
   - Announce means one push: title `FREE: <label>`, body the product title and
     the delivery text, click the product URL, priority `high`, tags
     `package,<slug>`.
   - On failure, that product's `fail_count` rises and its `last_error` is set;
     its last known good data stays in state and on the page.
4. Failure warnings, evaluated once at the end of the cycle:
   - A product "crosses" when its `fail_count` equals `FAIL_ALERT_AT` or is
     above it and `(fail_count - FAIL_ALERT_AT) % FAIL_REWARN_EVERY == 0`. This
     is today's rule, applied per product.
   - If every watched product failed this cycle and at least one crossed, send
     exactly one push: title `Amazon watcher failing`, body naming the number of
     products and the last error, tags `warning`. A systemic problem is one
     alert, not N.
   - Otherwise send one push per crossed product: title
     `Amazon watcher failing: <label>`, tags `warning,<slug>`.
   - Priority stays `default` for every warning.
5. Save state with `keep_asins` set to the watched ASINs, save history if it
   changed, render the page.

`run()` keeps its injectable seams so tests stay offline. Its `fetch` parameter
keeps the signature `fetch(asin) -> str`; the default builds a session, calls
`set_israel` once and returns a closure over it. A `products_path` parameter is
added beside the other paths.

An empty product list is not an error: the cycle records the timestamp, renders
an empty page and sends nothing.

### `render.py`

One card per product, then the global block:

- Cards sort free first, then by the order in `products.json`.
- Each card: the label as a heading linking to the product page, the state badge
  (`FREE shipping to Israel` / `Paid shipping` / `No data yet`), the delivery
  text, the merchant when known, the product's own last-success time, a failure
  warning when that product's `fail_count` is above zero, and that product's
  history rows.
- When no products are watched, the page says so and still shows the buttons.
- Below the cards: last checked, next automatic check, the "Check now" button as
  today, and a new "Manage products" button linking to `MANAGE_WORKFLOW_URL`,
  with one line explaining that it opens GitHub Actions where the user picks
  add or remove and pastes an ASIN or an Amazon link.
- Times stay Jerusalem local with UTC beside them, and the footer is unchanged.

### `manage.py` (new)

A command-line entry point run by the `manage` workflow. No network.

```
python -m watch.manage --action add|remove --product <asin or url> [--label "..."]
```

It loads `products.json`, applies the change, writes the file, prints one line
naming what changed, and exits 0. On `ProductError` it prints the message to
stderr and exits 1, leaving the file untouched, so the workflow fails visibly
and commits nothing.

## Workflow: `.github/workflows/manage.yml`

`workflow_dispatch` only, with inputs `action` (a choice of `add` and `remove`),
`product` (required, an ASIN or an Amazon URL) and `label` (optional). It checks
out, installs Python, runs `watch.manage`, and commits and pushes
`products.json` when it changed.

It does not poll. `poll.yml` gains `products.json` to its `push` path filter, so
the manage commit cancels the sleeping poll job and starts a fresh one, which
polls immediately. Adding a product therefore shows its state on the page about
a minute later, with no second button to press.

`poll.yml` also gains `products.json` to the paths it stages before committing,
for the case where a poll and a manage run race; the file is not written by the
poll, so this only ever stages nothing.

## Repository setup

No new secrets. No new permissions beyond `contents: write`, which `poll.yml`
already has.

## Testing

pytest, no network, as today.

- `test_products`: ASIN extracted from a bare ASIN, `/dp/`, `/gp/product/`, a
  URL with a query string, and lowercase input; a bad string raises; add rejects
  a duplicate; remove rejects an unknown ASIN; add and remove do not mutate the
  input; `display_label` prefers the label, then the truncated title, then the
  ASIN; `slug` folds punctuation, truncates, and falls back to the ASIN for a
  label with no ASCII alphanumerics.
- `test_state`: a version 1 file migrates under `DEFAULT_ASIN`; a version 2 file
  round-trips; `save` with `keep_asins` drops removed products; `entry` returns
  a default for an unknown ASIN without writing it.
- `test_history`: `append_flip` records the ASIN; a version 1 entry loads as
  `DEFAULT_ASIN`; `for_asin` filters.
- `test_client`: `set_israel` raises on a missing token and on an address-change
  failure; `fetch_page` raises on captcha, on a short body and on a glow line
  without Israel, and returns the HTML otherwise; `fetch_product` still works
  end to end against the fake session.
- `test_main`: two products flip independently and push once each with distinct
  tags; a product that fails keeps its previous data while the other updates;
  all products failing past the threshold sends exactly one combined warning;
  one product failing past the threshold sends one tagged warning; an empty
  product list writes the page and sends nothing; a removed product's state is
  dropped.
- `test_manage`: add writes the file; remove writes the file; a bad product
  string exits non-zero and leaves the file unchanged.
- `test_render`: a card per product; free sorts first; the manage button is
  present; an empty list renders the empty message and the buttons.

The existing fixtures are reused. A second fixture ASIN is not needed: the same
HTML is served for both products by the fake fetch.

## Out of scope

Per-product ntfy topics, per-product poll intervals, price tracking, reordering
products, a product limit, login, and pruning history for removed products.
